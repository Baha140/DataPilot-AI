
import json
from pathlib import Path
from datetime import datetime

import duckdb
import ollama
import pandas as pd

from datapilot.analysis.diagnostic import diagnose_table
from datapilot.analysis.quality_checks import run_quality_checks
from datapilot.analysis.cleaning import create_clean_tables
from datapilot.analysis.advanced_checks import analyze_monthly_prices

from datapilot.analysis.query_engine import QueryEngine
from datapilot.agent.sql_agent import (
    MODEL,
    generate_sql,
    validate_sql,
    correct_sql,
    generate_answer
)


# ============================================================
# CONFIGURATION
# ============================================================

BASE_DIR = Path(__file__).resolve().parents[3]
DB_PATH = BASE_DIR / "data" / "processed" / "datapilot.duckdb"

AVAILABLE_ACTIONS = {
    "diagnostic",
    "quality",
    "cleaning",
    "advanced_analysis",
    "sql",
    "unknown"
}

AVAILABLE_TABLES = {
    "stations",
    "prix",
    "ruptures",
    "all"
}

MAX_ACTIONS = 6
MAX_SQL_ATTEMPTS = 3


# ============================================================
# OUTILS GENERAUX
# ============================================================

def to_records(data):
    """
    Convertit un DataFrame ou une liste de dictionnaires
    en une liste de dictionnaires exploitable.
    """

    if isinstance(data, pd.DataFrame):
        return data.to_dict(orient="records")

    if isinstance(data, list):
        return data

    return []


def format_number(value):
    """Formate un nombre avec des espaces."""

    try:
        return f"{int(value):,}".replace(",", " ")
    except (ValueError, TypeError, OverflowError):
        return str(value)


def format_price(value):
    """Formate un prix avec trois décimales."""

    try:
        if value is None or pd.isna(value):
            return "Non disponible"

        return f"{float(value):.3f}"

    except (ValueError, TypeError):
        return str(value)


def get_table_names():
    """Retourne les tables disponibles dans DuckDB."""

    if not DB_PATH.exists():
        raise FileNotFoundError(
            f"Base de données introuvable : {DB_PATH}"
        )

    con = duckdb.connect(str(DB_PATH), read_only=True)

    try:
        rows = con.execute("""
            SELECT table_name
            FROM information_schema.tables
            WHERE table_schema = 'main'
        """).fetchall()

        return {row[0] for row in rows}

    finally:
        con.close()


def ensure_clean_tables():
    """
    Vérifie l'existence des tables nettoyées.
    Les crée si nécessaire.
    """

    required_tables = {
        "stations_clean",
        "prix_clean",
        "ruptures_clean"
    }

    existing_tables = get_table_names()

    missing_tables = required_tables - existing_tables

    if missing_tables:

        print(
            "\nCertaines tables nettoyées sont absentes : "
            f"{', '.join(sorted(missing_tables))}"
        )

        print("Préparation des tables nettoyées...")

        report = create_clean_tables()

        return {
            "nettoyage_effectue": True,
            "resultats_nettoyage": report
        }

    return {
        "nettoyage_effectue": False,
        "message": "Les tables nettoyées existent déjà."
    }


# ============================================================
# 1. PLANIFICATION MULTI-ACTIONS
# ============================================================


def fallback_plan(question):
    """
    Construit un plan de secours selon l'intention de l'utilisateur.
    Les demandes explicites sont traitées par priorité.
    """

    text = question.lower().strip()

    # 1. Demande de nettoyage
    if any(word in text for word in [
        "nettoie",
        "nettoyer",
        "nettoyage",
        "effectue le nettoyage",
        "nettoyer les données"
    ]):
        return [
            {"action": "diagnostic", "table": "all"},
            {"action": "quality", "table": "all"},
            {"action": "cleaning", "table": "all"}
        ]

    # 2. Analyse statistique avancée
    if any(word in text for word in [
        "anomalies mensuelles",
        "évolution mensuelle",
        "evolution mensuelle",
        "statistiques mensuelles",
        "analyse avancée",
        "analyse avancee",
        "analyse mensuelle",
        "tendance mensuelle"
    ]):
        return [
            {"action": "cleaning", "table": "all"},
            {"action": "advanced_analysis", "table": "prix"}
        ]

    # 3. Contrôle qualité et diagnostic
    if any(word in text for word in [
        "qualité",
        "qualite",
        "valeurs manquantes",
        "données manquantes",
        "donnees manquantes",
        "doublons",
        "diagnostic",
        "contrôle qualité",
        "controle qualite",
        "intégrité des données",
        "integrite des donnees",
        "anomalies"
    ]):
        return [
            {"action": "diagnostic", "table": "all"},
            {"action": "quality", "table": "all"}
        ]

    # 4. Questions nécessitant une requête SQL
    if any(word in text for word in [
        "prix",
        "carburant",
        "station",
        "ville",
        "rupture",
        "combien",
        "moyenne",
        "maximum",
        "minimum",
        "plus cher",
        "moins cher",
        "le moins coûteux",
        "le moins couteux",
        "le plus coûteux",
        "le plus couteux",
        "classement",
        "nombre de",
        "total de",
        "combien de",
        "évolution",
        "evolution",
        "comparer",
        "comparaison"
    ]):
        return [
            {"action": "sql", "table": "all"}
        ]

    return [
        {"action": "unknown", "table": "all"}
    ]


def plan_actions(question):

    print("\nDataPilot AI construit un plan d'exécution...")

    # --------------------------------------------------------
    # 1. PRIORITE AUX INTENTIONS CLAIRES
    # --------------------------------------------------------

    deterministic_plan = fallback_plan(question)

    if deterministic_plan[0]["action"] != "unknown":

        print(
            "\nIntention reconnue : utilisation du "
            "plan adapté à la demande."
        )

        validated_plan = deterministic_plan

    else:

        # ----------------------------------------------------
        # 2. PLANIFICATION AVEC QWEN POUR LES AUTRES DEMANDES
        # ----------------------------------------------------

        prompt = f"""
Tu es le planificateur intelligent de DataPilot AI.

Ta mission est de choisir UNIQUEMENT les actions nécessaires
pour répondre à la question de l'utilisateur.

ACTIONS DISPONIBLES :

- diagnostic : examiner les colonnes, les types,
  les valeurs manquantes et les doublons.
- quality : contrôler la qualité globale des données.
- cleaning : créer les tables nettoyées.
- advanced_analysis : analyser les prix mensuels
  et les anomalies statistiques mensuelles.
- sql : répondre à une question avec une requête SQL.
- unknown : demande non prise en charge.

TABLES :
stations, prix, ruptures, all.

REGLES IMPORTANTES :

1. Une question demandant une moyenne, un minimum,
   un maximum, un classement, un total, un comptage
   ou une comparaison utilise UNIQUEMENT sql.

2. Une question simple sur le prix d'un carburant
   utilise UNIQUEMENT sql.

3. Une question comme :
   "Quel est le carburant le moins cher en 2025 ?"
   utilise UNIQUEMENT sql.

4. Ne choisis jamais diagnostic, cleaning ou
   advanced_analysis pour une simple question SQL.

5. Une question sur les valeurs manquantes ou les doublons
   utilise diagnostic.

6. Une question sur la qualité générale des données
   utilise diagnostic et quality.

7. Une demande explicite de nettoyage utilise cleaning.
   Pour un nettoyage complet, utilise diagnostic,
   quality puis cleaning.

8. Une demande d'analyse statistique mensuelle ou
   d'identification des anomalies mensuelles utilise
   advanced_analysis.

9. advanced_analysis nécessite les tables nettoyées.
   Place cleaning avant advanced_analysis.

10. Ne répète pas les actions.

11. Ne réalise pas d'actions inutiles.

12. Ne dépasse pas six actions.

13. Retourne uniquement un JSON valide.

EXEMPLES :

Question : Quel est le carburant le moins cher en 2025 ?
Réponse :
{{"plan":[{{"action":"sql","table":"all"}}]}}

Question : Combien de ruptures existe-t-il par carburant ?
Réponse :
{{"plan":[{{"action":"sql","table":"all"}}]}}

Question : Quelles sont les valeurs manquantes dans stations ?
Réponse :
{{"plan":[{{"action":"diagnostic","table":"stations"}}]}}

Question : Contrôle la qualité globale des données.
Réponse :
{{"plan":[{{"action":"diagnostic","table":"all"}},{{"action":"quality","table":"all"}}]}}

Question : Analyse l'évolution mensuelle des prix et les anomalies.
Réponse :
{{"plan":[{{"action":"cleaning","table":"all"}},{{"action":"advanced_analysis","table":"all"}}]}}

QUESTION UTILISATEUR :
{question}

FORMAT OBLIGATOIRE :

{{"plan":[{{"action":"sql","table":"all"}}]}}
"""

        try:

            response = ollama.chat(
                model=MODEL,
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "Tu es le planificateur de DataPilot AI. "
                            "Retourne uniquement un JSON valide "
                            "respectant les règles et les exemples."
                        )
                    },
                    {
                        "role": "user",
                        "content": prompt
                    }
                ],
                format="json",
                options={"temperature": 0}
            )

            content = response["message"]["content"]
            result = json.loads(content)

            if not isinstance(result, dict):
                raise ValueError("Le résultat JSON doit être un objet.")

            raw_plan = result.get("plan", [])

            if not isinstance(raw_plan, list) or not raw_plan:
                raise ValueError("Le plan retourné est vide ou invalide.")

        except Exception as error:

            print(f"\nPlanification Qwen impossible : {error}")
            print("Utilisation du plan de secours.")

            raw_plan = fallback_plan(question)

        # ----------------------------------------------------
        # 3. VALIDATION DU PLAN DE QWEN
        # ----------------------------------------------------

        validated_plan = []
        seen = set()

        for step in raw_plan:

            if not isinstance(step, dict):
                continue

            action = step.get("action", "unknown")
            table = step.get("table", "all")

            if not isinstance(action, str):
                continue

            if action not in AVAILABLE_ACTIONS:
                continue

            if action == "unknown":
                continue

            if not isinstance(table, str):
                table = "all"

            if table not in AVAILABLE_TABLES:
                table = "all"

            # Seul le diagnostic accepte une table précise.
            if action != "diagnostic":
                table = "all"

            key = (action, table)

            if key in seen:
                continue

            validated_plan.append({
                "action": action,
                "table": table
            })

            seen.add(key)

        # Aucun plan exploitable : retour au plan de secours.
        if not validated_plan:
            validated_plan = fallback_plan(question)

        # ----------------------------------------------------
        # 4. VERIFICATION DES PRE-REQUIS
        # ----------------------------------------------------

        if any(
            step["action"] == "advanced_analysis"
            for step in validated_plan
        ):

            has_cleaning = any(
                step["action"] == "cleaning"
                for step in validated_plan
            )

            if not has_cleaning:

                advanced_index = next(
                    index
                    for index, step in enumerate(validated_plan)
                    if step["action"] == "advanced_analysis"
                )

                validated_plan.insert(
                    advanced_index,
                    {
                        "action": "cleaning",
                        "table": "all"
                    }
                )

        validated_plan = validated_plan[:MAX_ACTIONS]

    # --------------------------------------------------------
    # 5. AFFICHAGE DU PLAN
    # --------------------------------------------------------

    print("\nPlan d'exécution proposé par DataPilot AI :")

    for index, step in enumerate(validated_plan, start=1):

        print(
            f"{index}. Action : {step['action']} "
            f"| Table : {step['table']}"
        )

    return validated_plan



# ============================================================
# 2. DIAGNOSTIC
# ============================================================

def execute_diagnostic(table):

    print("\nDémarrage du diagnostic des données...")

    tables = (
        ["stations", "prix", "ruptures"]
        if table == "all"
        else [table]
    )

    report = {}

    for table_name in tables:

        print(f"\nDiagnostic de la table : {table_name}")

        result = diagnose_table(table_name)

        report[table_name] = result

    print("\nDiagnostic terminé.")

    return report


# ============================================================
# 3. CONTROLE QUALITE
# ============================================================

def execute_quality():

    print("\nDémarrage du contrôle qualité...")

    report = run_quality_checks()

    print("\nContrôle qualité terminé.")

    return report


# ============================================================
# 4. NETTOYAGE
# ============================================================

def execute_cleaning():

    print("\nDémarrage du nettoyage des données...")

    report = create_clean_tables()

    print("\nNettoyage terminé.")
    print("Les tables originales sont conservées.")

    return report


# ============================================================
# 5. ANALYSE AVANCEE
# ============================================================

def execute_advanced_analysis():

    print("\nDémarrage de l'analyse avancée...")

    prerequisites = ensure_clean_tables()

    report = analyze_monthly_prices()

    if not isinstance(report, dict):

        raise ValueError(
            "Le module advanced_checks n'a pas retourné "
            "un dictionnaire de résultats."
        )

    report["_prerequis"] = prerequisites

    print("\nAnalyse avancée terminée.")

    return report


# ============================================================
# 6. ANALYSE SQL
# ============================================================

def execute_sql(question):

    engine = QueryEngine()

    try:

        print("\nGénération de la requête SQL...")

        sql, explanation = generate_sql(question)

        result = None

        for attempt in range(1, MAX_SQL_ATTEMPTS + 1):

            print(f"\nTentative {attempt}/{MAX_SQL_ATTEMPTS}")
            print("\nRequête SQL :")
            print(sql)

            try:

                validated_sql = validate_sql(sql)

                result = engine.execute_query(validated_sql)

                print("\nRequête exécutée avec succès.")
                break

            except Exception as error:

                print(f"\nErreur SQL : {error}")

                if attempt == MAX_SQL_ATTEMPTS:
                    break

                sql, explanation = correct_sql(
                    question,
                    sql,
                    str(error)
                )

        if result is None:
            print("\nImpossible d'obtenir un résultat SQL.")
            return False, None

        print("\nRésultat :")
        print(result.head(20).to_string(index=False))

        print("\nInterprétation par Qwen...")

        answer = generate_answer(
            question,
            sql,
            explanation,
            result
        )

        print("\nRéponse de DataPilot AI :")
        print(answer)

        structured_result = {
            "requete_sql": sql,
            "explication": explanation,
            "interpretation": answer,
            "nombre_total_lignes": len(result),
            "resultats": result.head(20).to_dict(orient="records")
        }

        return True, structured_result

    finally:
        engine.close()


# ============================================================
# 7. EXECUTION D'UNE ACTION
# ============================================================

def execute_action(step, question):

    action = step["action"]
    table = step["table"]

    if action == "diagnostic":

        return True, execute_diagnostic(table)

    if action == "quality":

        return True, execute_quality()

    if action == "cleaning":

        return True, execute_cleaning()

    if action == "advanced_analysis":

        return True, execute_advanced_analysis()

    if action == "sql":

        return execute_sql(question)

    print("\nAction non reconnue.")

    return False, None


# ============================================================
# 8. INTERPRETATION FACTUELLE DE L'ANALYSE AVANCEE
# ============================================================

def generate_advanced_interpretation(advanced_data):
    """
    Produit une interprétation numérique déterministe.
    Les chiffres sont calculés par Python, pas inventés par Qwen.
    """

    monthly_stats = to_records(
        advanced_data.get("statistiques_mensuelles", [])
    )

    monthly_anomalies = to_records(
        advanced_data.get("anomalies_mensuelles", [])
    )

    ruptures = advanced_data.get(
        "ruptures_dates_incoherentes",
        []
    )

    lines = []

    # Evolution des prix.
    evolution = {}

    for item in monthly_stats:

        fuel = item.get("carburant")
        month = str(item.get("mois", ""))[:10]

        try:
            average = float(item.get("prix_moyen"))
        except (ValueError, TypeError):
            continue

        if fuel and month:
            evolution.setdefault(fuel, []).append(
                (month, average)
            )

    lines.append("#### Évolution des prix moyens")

    if evolution:

        for fuel, values in sorted(evolution.items()):

            values.sort(key=lambda item: item[0])

            first_month, first_price = values[0]
            last_month, last_price = values[-1]

            variation = last_price - first_price

            if variation > 0:
                direction = "une hausse"
            elif variation < 0:
                direction = "une baisse"
            else:
                direction = "une stabilité"

            lines.append(
                f"- **{fuel}** : {direction} entre "
                f"{first_month} et {last_month}. "
                f"Le prix moyen passe de "
                f"{format_price(first_price)} à "
                f"{format_price(last_price)}, soit une variation "
                f"de {format_price(variation)}."
            )

    else:

        lines.append(
            "- Les données nécessaires à l'étude de l'évolution "
            "des prix ne sont pas disponibles."
        )

    # Anomalies.
    anomalies_by_fuel = {}
    anomalies_by_month = {}

    for item in monthly_anomalies:

        fuel = item.get("carburant", "Inconnu")
        month = str(item.get("mois", "Inconnu"))[:10]

        try:
            count = int(item.get("nombre_anomalies", 0))
        except (ValueError, TypeError):
            continue

        anomalies_by_fuel[fuel] = (
            anomalies_by_fuel.get(fuel, 0) + count
        )

        anomalies_by_month[month] = (
            anomalies_by_month.get(month, 0) + count
        )

    lines.append("\n#### Répartition des anomalies statistiques")

    total_anomalies = sum(anomalies_by_fuel.values())

    lines.append(
        f"- Nombre total d'observations inhabituelles "
        f"dans l'analyse mensuelle : "
        f"**{format_number(total_anomalies)}**."
    )

    if anomalies_by_fuel:

        top_fuel = max(
            anomalies_by_fuel.items(),
            key=lambda item: item[1]
        )

        lines.append(
            f"- Le carburant présentant le plus d'anomalies "
            f"est **{top_fuel[0]}**, avec "
            f"{format_number(top_fuel[1])} observations."
        )

    if anomalies_by_month:

        top_month = max(
            anomalies_by_month.items(),
            key=lambda item: item[1]
        )

        lines.append(
            f"- Le mois présentant le plus d'anomalies est "
            f"**{top_month[0]}**, avec "
            f"{format_number(top_month[1])} observations."
        )

    lines.append(
        "- Les anomalies IQR sont des observations "
        "statistiquement inhabituelles. Elles ne constituent "
        "pas nécessairement des erreurs."
    )

    # Ruptures incohérentes.
    if isinstance(ruptures, list):
        rupture_count = len(ruptures)
    elif isinstance(ruptures, (int, float)):
        rupture_count = int(ruptures)
    else:
        rupture_count = 0

    lines.append("\n#### Cohérence des ruptures")

    lines.append(
        f"- Nombre de ruptures avec des dates incohérentes : "
        f"**{format_number(rupture_count)}**."
    )

    if rupture_count > 0:

        lines.append(
            "- Ces enregistrements nécessitent une vérification "
            "des dates dans les données sources."
        )

    return "\n".join(lines)


# ============================================================
# 9. GENERATION DU RAPPORT
# ============================================================

def generate_report(question, execution_results):

    print("\n" + "=" * 60)
    print("       GENERATION DU RAPPORT FINAL")
    print("=" * 60)

    diagnostic_data = {}
    quality_data = {}
    cleaning_data = {}
    advanced_data = {}

    for item in execution_results:

        if item.get("status") != "REUSSIE":
            continue

        action = item.get("action")
        data = item.get("data")

        if action == "diagnostic" and isinstance(data, dict):
            diagnostic_data.update(data)

        elif action == "quality" and isinstance(data, dict):
            quality_data = data

        elif action == "cleaning" and isinstance(data, dict):
            cleaning_data = data

        elif action == "advanced_analysis" and isinstance(data, dict):
            advanced_data = data

    sections = []

    sections.append("# Rapport DataPilot AI\n")
    sections.append(f"**Question utilisateur :** {question}\n")
    sections.append(
        f"**Date de génération :** "
        f"{datetime.now().strftime('%d/%m/%Y %H:%M:%S')}\n"
    )

    # --------------------------------------------------------
    # DIAGNOSTIC
    # --------------------------------------------------------

    if diagnostic_data:

        sections.append("\n## 1. Diagnostic des données\n")

        for table_name, info in diagnostic_data.items():

            sections.append(f"\n### Table `{table_name}`\n")

            sections.append(
                f"- Nombre de lignes : "
                f"{format_number(info.get('total_rows', 0))}\n"
            )

            sections.append(
                f"- Nombre de colonnes : "
                f"{format_number(info.get('total_columns', 0))}\n"
            )

            missing_values = info.get("missing_values", [])

            missing_dict = {}

            if (
                isinstance(missing_values, list)
                and missing_values
                and isinstance(missing_values[0], dict)
            ):
                missing_dict = missing_values[0]

            missing_columns = {
                column: count
                for column, count in missing_dict.items()
                if isinstance(count, (int, float)) and count > 0
            }

            sections.append("\n**Valeurs manquantes :**\n")

            if missing_columns:

                for column, count in missing_columns.items():

                    percentage = (
                        count / info["total_rows"] * 100
                        if info.get("total_rows", 0)
                        else 0
                    )

                    sections.append(
                        f"- `{column}` : {format_number(count)} "
                        f"({percentage:.2f} %)\n"
                    )

            else:

                sections.append("- Aucune valeur manquante.\n")

            sections.append(
                f"- Groupes de doublons : "
                f"{format_number(info.get('duplicate_groups', 0))}\n"
            )

    # --------------------------------------------------------
    # QUALITE
    # --------------------------------------------------------

    if quality_data:

        sections.append("\n## 2. Contrôle qualité\n")

        sections.append("\n### Contrôle des prix\n")

        sections.append(
            f"- Prix manquants : "
            f"{format_number(quality_data.get('prix_manquants', 0))}\n"
        )

        sections.append(
            f"- Prix égaux à zéro : "
            f"{format_number(quality_data.get('prix_nuls', 0))}\n"
        )

        sections.append(
            f"- Prix négatifs : "
            f"{format_number(quality_data.get('prix_negatifs', 0))}\n"
        )

        sections.append(
            f"- Anomalies statistiques IQR : "
            f"{format_number(quality_data.get('nombre_total_anomalies', 0))}\n"
        )

        anomalies = to_records(
            quality_data.get("anomalies_prix", [])
        )

        if anomalies:

            sections.append(
                "\n| Carburant | Nombre d'anomalies |\n"
                "|---|---:|\n"
            )

            for item in anomalies:

                sections.append(
                    f"| {item.get('carburant', 'Inconnu')} "
                    f"| {format_number(item.get('nombre_anomalies', 0))} |\n"
                )

        sections.append("\n### Contrôle des dates\n")

        sections.append(
            f"- Première date : "
            f"{quality_data.get('date_minimum', 'Non disponible')}\n"
        )

        sections.append(
            f"- Dernière date : "
            f"{quality_data.get('date_maximum', 'Non disponible')}\n"
        )

        sections.append(
            f"- Dates manquantes : "
            f"{format_number(quality_data.get('dates_manquantes', 0))}\n"
        )

        sections.append(
            f"- Ruptures avec dates incohérentes : "
            f"{format_number(quality_data.get('ruptures_dates_incoherentes', 0))}\n"
        )

        sections.append("\n### Intégrité référentielle\n")

        for label, key in [
            ("Identifiants de station manquants dans les prix",
             "references_prix_manquantes"),
            ("Identifiants de station manquants dans les ruptures",
             "references_ruptures_manquantes"),
            ("Prix liés à une station inexistante",
             "prix_sans_station"),
            ("Ruptures liées à une station inexistante",
             "ruptures_sans_station")
        ]:

            sections.append(
                f"- {label} : "
                f"{format_number(quality_data.get(key, 0))}\n"
            )

        sections.append("\n### Coordonnées\n")

        for label, key in [
            ("Latitude minimale", "latitude_minimum"),
            ("Latitude maximale", "latitude_maximum"),
            ("Longitude minimale", "longitude_minimum"),
            ("Longitude maximale", "longitude_maximum")
        ]:

            sections.append(
                f"- {label} : {quality_data.get(key, 'Non disponible')}\n"
            )

        sections.append(
            f"- Stations avec coordonnées manquantes : "
            f"{format_number(quality_data.get('coordonnees_manquantes', 0))}\n"
        )

        sections.append(
            "\nLe système de référence des coordonnées doit être confirmé "
            "avant toute interprétation géographique.\n"
        )

    # --------------------------------------------------------
    # NETTOYAGE
    # --------------------------------------------------------

    if cleaning_data:

        sections.append("\n## 3. Résultats du nettoyage\n")

        for table_name in [
            "stations_clean",
            "prix_clean",
            "ruptures_clean"
        ]:

            info = cleaning_data.get(table_name)

            if not isinstance(info, dict):
                continue

            sections.append(f"\n### `{table_name}`\n")

            sections.append(
                f"- Nombre de lignes : "
                f"{format_number(info.get('total_lignes', 0))}\n"
            )

            statuses = info.get("statuts", {})

            if statuses:

                sections.append(
                    "\n| Statut | Nombre de lignes |\n"
                    "|---|---:|\n"
                )

                for status, count in statuses.items():

                    sections.append(
                        f"| {status} | {format_number(count)} |\n"
                    )

            indicators = info.get("indicateurs", {})

            if indicators:

                sections.append("\n**Indicateurs détaillés :**\n")

                for name, value in indicators.items():

                    sections.append(
                        f"- {name} : {format_number(value)}\n"
                    )

        conservation = cleaning_data.get(
            "conservation_donnees"
        )

        if conservation is True:

            sections.append(
                "\n**Conservation :** toutes les lignes originales "
                "ont été conservées dans les tables nettoyées.\n"
            )

        elif conservation is False:

            sections.append(
                "\n**Attention :** une différence de nombre de lignes "
                "a été détectée.\n"
            )

        sections.append(
            "\nLe nettoyage prépare des tables propres et ajoute "
            "des indicateurs de qualité. Il ne signifie pas que "
            "toutes les anomalies ont été corrigées.\n"
        )

    # --------------------------------------------------------
    # ANALYSE AVANCEE
    # --------------------------------------------------------

    if advanced_data:

        sections.append("\n## 4. Analyse avancée\n")

        monthly_stats = to_records(
            advanced_data.get("statistiques_mensuelles", [])
        )

        if monthly_stats:

            sections.append("\n### Statistiques mensuelles des prix\n")

            sections.append(
                "| Mois | Carburant | Nombre de prix | "
                "Prix moyen | Minimum | Maximum |\n"
                "|---|---|---:|---:|---:|---:|\n"
            )

            for item in monthly_stats:

                sections.append(
                    f"| {str(item.get('mois', 'Inconnu'))[:10]} "
                    f"| {item.get('carburant', 'Inconnu')} "
                    f"| {format_number(item.get('nombre_prix', 0))} "
                    f"| {format_price(item.get('prix_moyen'))} "
                    f"| {format_price(item.get('prix_minimum'))} "
                    f"| {format_price(item.get('prix_maximum'))} |\n"
                )

        monthly_anomalies = to_records(
            advanced_data.get("anomalies_mensuelles", [])
        )

        if monthly_anomalies:

            sections.append("\n### Anomalies par mois\n")

            sections.append(
                "| Mois | Carburant | Nombre d'anomalies |\n"
                "|---|---|---:|\n"
            )

            total_anomalies = 0

            for item in monthly_anomalies:

                count = int(item.get("nombre_anomalies", 0) or 0)
                total_anomalies += count

                sections.append(
                    f"| {str(item.get('mois', 'Inconnu'))[:10]} "
                    f"| {item.get('carburant', 'Inconnu')} "
                    f"| {format_number(count)} |\n"
                )

            sections.append(
                f"\n**Total : {format_number(total_anomalies)} "
                "observations statistiquement inhabituelles.**\n"
            )

            sections.append(
                "\nUne anomalie IQR est une observation statistiquement "
                "inhabituelle, pas nécessairement une erreur.\n"
            )

        ruptures = advanced_data.get(
            "ruptures_dates_incoherentes",
            []
        )

        if isinstance(ruptures, list) and ruptures:

            sections.append(
                "\n### Ruptures avec dates incohérentes\n"
            )

            sections.append(
                "| Station | Carburant | Date début | Date fin | Type |\n"
                "|---|---|---|---|---|\n"
            )

            for item in ruptures:

                sections.append(
                    f"| {item.get('station_id', 'Inconnu')} "
                    f"| {item.get('carburant', 'Inconnu')} "
                    f"| {item.get('date_debut', 'Inconnue')} "
                    f"| {item.get('date_fin', 'Inconnue')} "
                    f"| {item.get('type', 'Inconnu')} |\n"
                )

        # Résumé avancé.
        summary = advanced_data.get("resume", {})

        if isinstance(summary, dict) and summary:

            sections.append("\n### Synthèse statistique\n")

            for key, label in [
                ("nombre_groupes_mensuels",
                 "Groupes de statistiques mensuelles"),
                ("nombre_groupes_anomalies",
                 "Groupes d'anomalies mensuelles"),
                ("nombre_ruptures_incoherentes",
                 "Ruptures incohérentes")
            ]:

                if key in summary:

                    sections.append(
                        f"- {label} : "
                        f"{format_number(summary[key])}\n"
                    )

        sections.append(
            "\n### Interprétation des résultats\n\n"
        )

        sections.append(
            generate_advanced_interpretation(advanced_data)
        )

        sections.append(
            "\n\nL'analyse statistique identifie des observations "
            "inhabituelles. Une vérification métier est nécessaire "
            "avant de conclure à une erreur.\n"
        )

    # --------------------------------------------------------
    # RECOMMANDATIONS
    # --------------------------------------------------------

    recommendations = []

    for table_name, info in diagnostic_data.items():

        missing_values = info.get("missing_values", [])

        if (
            isinstance(missing_values, list)
            and missing_values
            and isinstance(missing_values[0], dict)
        ):

            for column, count in missing_values[0].items():

                if isinstance(count, (int, float)) and count > 0:

                    recommendations.append(
                        f"Vérifier les {format_number(count)} valeurs "
                        f"manquantes de la colonne `{column}` "
                        f"dans la table `{table_name}`."
                    )

    if quality_data.get("nombre_total_anomalies", 0) > 0:

        recommendations.append(
            "Examiner les prix statistiquement inhabituels par "
            "carburant et par période avant toute correction."
        )

    if quality_data.get("ruptures_dates_incoherentes", 0) > 0:

        recommendations.append(
            "Vérifier les ruptures dont la date de fin est "
            "antérieure à la date de début."
        )

    if quality_data.get("coordonnees_manquantes", 0) > 0:

        recommendations.append(
            "Compléter et vérifier les coordonnées manquantes "
            "des stations à partir des sources originales."
        )

    if quality_data:

        recommendations.append(
            "Confirmer le système de référence des coordonnées "
            "avant toute exploitation cartographique."
        )

    if cleaning_data:

        recommendations.append(
            "Conserver les tables originales et effectuer les "
            "corrections uniquement après validation."
        )

    if recommendations:

        sections.append("\n## 5. Recommandations\n")

        for index, recommendation in enumerate(
            recommendations,
            start=1
        ):

            sections.append(
                f"{index}. {recommendation}\n"
            )

    # --------------------------------------------------------
    # BILAN D'EXECUTION
    # --------------------------------------------------------

    sections.append("\n## 6. Bilan de l'exécution\n")

    for item in execution_results:

        sections.append(
            f"- Action `{item.get('action')}` "
            f"sur `{item.get('table')}` : "
            f"**{item.get('status')}**"
        )

        if item.get("error"):
            sections.append(
                f" — Erreur : {item['error']}"
            )

        sections.append("\n")

    sections.append(
        "\n---\n\n"
        "*Rapport généré automatiquement par DataPilot AI.*\n"
    )

    # --------------------------------------------------------
    # ENREGISTREMENT
    # --------------------------------------------------------

    report_text = "".join(sections)

    reports_dir = BASE_DIR / "data" / "processed" / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    report_path = (
        reports_dir / f"rapport_datapilot_{timestamp}.md"
    )

    report_path.write_text(
        report_text,
        encoding="utf-8"
    )

    print("\nRapport généré avec succès !")
    print(f"Emplacement : {report_path}")

    return report_path


# ============================================================
# 10. EXECUTION DU PLAN COMPLET
# ============================================================

def execute_plan(plan, question):

    print("\n" + "=" * 60)
    print("       EXECUTION DU PLAN MULTI-ACTIONS")
    print("=" * 60)

    results = []

    for index, step in enumerate(plan, start=1):

        action = step["action"]

        print("\n" + "-" * 60)
        print(f"ETAPE {index}/{len(plan)} : {action.upper()}")
        print("-" * 60)

        data = None
        error_message = None

        try:

            success, data = execute_action(step, question)

            status = "REUSSIE" if success else "ECHEC"

        except Exception as error:

            error_message = str(error)

            print(
                f"\nErreur pendant l'action {action} : "
                f"{error_message}"
            )

            status = "ECHEC"

        results.append({
            "action": action,
            "table": step["table"],
            "status": status,
            "data": data,
            "error": error_message
        })

    # --------------------------------------------------------
    # BILAN
    # --------------------------------------------------------

    print("\n" + "=" * 60)
    print("          BILAN DE L'EXECUTION")
    print("=" * 60)

    for result in results:

        print(
            f"- {result['action']} "
            f"({result['table']}) : {result['status']}"
        )

    successful = sum(
        1 for result in results
        if result["status"] == "REUSSIE"
    )

    failed = len(results) - successful

    print("\nActions réussies :", successful)
    print("Actions échouées :", failed)

    if failed == 0:
        print("\nPlan exécuté avec succès !")
    else:
        print("\nPlan terminé avec certaines erreurs.")

    # --------------------------------------------------------
    # RAPPORT
    # --------------------------------------------------------

    report_actions = {
        "diagnostic",
        "quality",
        "cleaning",
        "advanced_analysis"
    }

    should_generate_report = (
        any(
            result["action"] in report_actions
            for result in results
        )
        and successful > 0
    )

    if should_generate_report:

        try:

            # On transmet tous les résultats, y compris les échecs.
            report_path = generate_report(
                question,
                results
            )

            print(
                f"\nRapport disponible : {report_path}"
            )

        except Exception as error:

            print(
                "\nErreur pendant la génération du rapport : "
                f"{error}"
            )

    return results


# ============================================================
# 11. LANCEMENT PRINCIPAL
# ============================================================

def run_orchestrator():

    print("\n" + "=" * 60)
    print("              DATAPILOT AI")
    print("       AGENT INTELLIGENT D'ANALYSE")
    print("=" * 60)

    print("\nBienvenue dans DataPilot AI !")
    print("Posez vos questions sur vos données.")
    print("Tapez 'exit' ou 'quit' pour quitter.")

    while True:

        print("\n" + "-" * 60)

        question = input("\nVotre question : ").strip()

        if question.lower() in ["exit", "quit", "q"]:

            print("\nFermeture de DataPilot AI...")
            print("Au revoir !")
            break

        if not question:

            print("\nVeuillez saisir une question.")
            continue

        try:

            plan = plan_actions(question)

            if (
                len(plan) == 1
                and plan[0]["action"] == "unknown"
            ):

                print(
                    "\nJe ne peux pas traiter cette demande "
                    "avec les fonctionnalités actuelles."
                )

                continue

            execute_plan(plan, question)

        except KeyboardInterrupt:

            print("\n\nInterruption demandée.")
            break

        except Exception as error:

            print("\nUne erreur est survenue :")
            print(error)

            print(
                "\nVous pouvez réessayer avec une autre question."
            )


if __name__ == "__main__":
    run_orchestrator()
