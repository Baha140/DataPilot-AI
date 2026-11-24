
import json
import re

import ollama
import pandas as pd

from datapilot.analysis.query_engine import QueryEngine


MODEL = "qwen2.5:3b"

ALLOWED_TABLES = {
    "stations_clean",
    "prix_clean",
    "ruptures_clean"
}

MAX_ATTEMPTS = 3
MAX_PREVIEW_ROWS = 20


SYSTEM_PROMPT = """
Tu es DataPilot AI, un agent intelligent spécialisé
dans l'analyse de données avec SQL DuckDB.

Tu travailles sur une base contenant trois tables :

1. stations_clean :
station_id, latitude, longitude, code_postal,
population_type, adresse, ville, fermee,
qualite_coordonnees

2. prix_clean :
station_id, carburant, carburant_id, date_maj,
prix, qualite_statut

3. ruptures_clean :
station_id, carburant, carburant_id, date_debut,
date_fin, type, qualite_statut

==================================================
REGLES D'ANALYSE
==================================================

1. PRIX MOYEN

Pour comparer les prix des carburants, utiliser AVG(prix).

2. CARBURANT LE MOINS CHER

Calculer le prix moyen de chaque carburant,
puis trier par prix moyen croissant.

3. CARBURANTS LES PLUS CHERS

Calculer le prix moyen par carburant,
puis trier par prix moyen décroissant.

4. EVOLUTION DES PRIX

Pour une évolution mensuelle :
DATE_TRUNC('month', date_maj)

Pour une évolution annuelle :
DATE_TRUNC('year', date_maj)

Toujours filtrer le carburant demandé.

Ne jamais grouper par date_maj complète
pour une évolution mensuelle.

5. PERIODE 2025

Utiliser :

date_maj >= '2025-01-01'
AND date_maj < '2026-01-01'

6. DONNEES MANQUANTES

Pour les comparaisons par carburant :
carburant IS NOT NULL

Pour les prix moyens :
prix IS NOT NULL

7. RUPTURES

Pour compter les ruptures :
COUNT(*)

Grouper par carburant si demandé.

8. SECURITE

- Générer uniquement une requête SELECT.
- Utiliser uniquement les trois tables autorisées.
- Ne jamais modifier les données.
- Ne jamais inventer de colonnes.
- Ne jamais générer plusieurs requêtes.
- Ne pas utiliser de CTE.
- Ne pas utiliser de sous-requêtes.
- Ne pas utiliser de fonctions externes.
- Ne pas lire de fichiers.
- Ne pas utiliser de tables non autorisées.

==================================================
EXEMPLES
==================================================

Question :
Quel est le carburant le moins cher en 2025 ?

SQL :
SELECT carburant, AVG(prix) AS prix_moyen
FROM prix_clean
WHERE date_maj >= '2025-01-01'
AND date_maj < '2026-01-01'
AND carburant IS NOT NULL
AND prix IS NOT NULL
GROUP BY carburant
ORDER BY prix_moyen ASC
LIMIT 1

Question :
Comment a évolué le prix du Gazole en 2025 ?

SQL :
SELECT
    DATE_TRUNC('month', date_maj) AS mois,
    AVG(prix) AS prix_moyen
FROM prix_clean
WHERE carburant = 'Gazole'
AND date_maj >= '2025-01-01'
AND date_maj < '2026-01-01'
AND prix IS NOT NULL
GROUP BY DATE_TRUNC('month', date_maj)
ORDER BY mois

Question :
Quels sont les cinq carburants les plus chers ?

SQL :
SELECT
    carburant,
    AVG(prix) AS prix_moyen
FROM prix_clean
WHERE carburant IS NOT NULL
AND prix IS NOT NULL
GROUP BY carburant
ORDER BY prix_moyen DESC
LIMIT 5

==================================================
FORMAT DE REPONSE
==================================================

Retourner exclusivement un objet JSON :

{
    "sql": "SELECT ...",
    "explanation": "Explication courte"
}
"""


def parse_model_json(response):
    """
    Vérifie et décode la réponse JSON de Qwen.
    """

    try:
        content = response["message"]["content"]
    except (KeyError, TypeError):
        raise ValueError("Réponse Ollama invalide ou incomplète.")

    try:
        result = json.loads(content)
    except (json.JSONDecodeError, TypeError):
        raise ValueError("Qwen a retourné un JSON invalide.")

    if not isinstance(result, dict):
        raise ValueError("La réponse de Qwen doit être un objet JSON.")

    sql = result.get("sql")
    explanation = result.get("explanation", "")

    if not isinstance(sql, str) or not sql.strip():
        raise ValueError("Qwen n'a pas fourni de requête SQL valide.")

    if not isinstance(explanation, str):
        explanation = ""

    return sql.strip(), explanation.strip()


def generate_sql(question):
    """
    Génère une requête SQL à partir d'une question en français.
    """

    if not isinstance(question, str) or not question.strip():
        raise ValueError("La question ne peut pas être vide.")

    response = ollama.chat(
        model=MODEL,
        messages=[
            {
                "role": "system",
                "content": SYSTEM_PROMPT
            },
            {
                "role": "user",
                "content": question.strip()
            }
        ],
        format="json",
        options={
            "temperature": 0
        }
    )

    return parse_model_json(response)


def correct_sql(question, previous_sql, error):
    """
    Demande à Qwen de corriger une requête SQL qui a échoué.
    """

    print("\nQwen analyse l'erreur et prépare une correction...")

    response = ollama.chat(
        model=MODEL,
        messages=[
            {
                "role": "system",
                "content": SYSTEM_PROMPT
            },
            {
                "role": "user",
                "content": f"""
La requête SQL suivante a échoué.

Question de l'utilisateur :
{question}

Requête SQL incorrecte :
{previous_sql}

Erreur rencontrée :
{error}

Ta mission :
1. Analyse l'erreur.
2. Corrige la requête SQL.
3. Conserve l'objectif initial.
4. Utilise uniquement les tables et colonnes autorisées.
5. Génère uniquement une requête SELECT.
6. N'utilise ni CTE ni sous-requête.
7. Ne modifie jamais les données.

Retourne obligatoirement un JSON contenant :
- sql : la requête SQL corrigée
- explanation : une courte explication de la correction

Ne retourne aucun texte en dehors du JSON.
"""
            }
        ],
        format="json",
        options={
            "temperature": 0
        }
    )

    return parse_model_json(response)


def remove_sql_string_literals(sql):
    """
    Remplace le contenu des chaînes SQL entre apostrophes
    par des espaces afin de ne pas confondre leur contenu
    avec des instructions SQL.

    Exemple :
    WHERE carburant = 'DELETE'

    Le mot DELETE ne sera pas considéré comme une instruction.
    """

    return re.sub(
        r"'(?:''|[^'])*'",
        " ",
        sql
    )


def has_top_level_from_comma(sql):
    """
    Détecte les virgules séparant plusieurs tables dans FROM.

    Exemple interdit :
    FROM prix_clean, stations

    Les virgules dans les fonctions entre parenthèses
    ne sont pas considérées comme des séparateurs de tables.
    """

    clause_end_keywords = {
        "WHERE",
        "GROUP",
        "ORDER",
        "HAVING",
        "LIMIT",
        "OFFSET",
        "QUALIFY",
        "WINDOW",
        "UNION",
        "EXCEPT",
        "INTERSECT"
    }

    from_positions = list(
        re.finditer(r"\bFROM\b", sql, re.IGNORECASE)
    )

    for match in from_positions:

        depth = 0
        position = match.end()

        while position < len(sql):

            char = sql[position]

            if char == "(":
                depth += 1

            elif char == ")":
                depth -= 1

            elif depth == 0:

                if char == ",":
                    return True

                keyword_match = re.match(
                    r"[A-Za-z_][A-Za-z0-9_]*",
                    sql[position:]
                )

                if keyword_match:

                    keyword = keyword_match.group(0).upper()

                    if keyword in clause_end_keywords:
                        break

                    position += len(keyword_match.group(0))
                    continue

            position += 1

    return False


def validate_sql(sql):
    """
    Validation conservatrice des requêtes SQL.

    Autorise uniquement :
    - SELECT
    - Les trois tables autorisées
    - Une seule instruction
    - Les requêtes sans CTE ni sous-requête

    La sécurité est également assurée par QueryEngine,
    qui utilise DuckDB en lecture seule et désactive
    l'accès externe.
    """

    if not isinstance(sql, str):
        raise ValueError("La requête SQL doit être une chaîne de caractères.")

    sql = sql.strip()

    if not sql:
        raise ValueError("La requête SQL est vide.")

    # Autoriser un seul point-virgule final.
    if sql.endswith(";"):
        sql = sql[:-1].rstrip()

    # Interdire tout autre point-virgule.
    if ";" in sql:
        raise ValueError("Une seule requête SQL est autorisée.")

    # Interdire les commentaires SQL.
    if "--" in sql or "/*" in sql or "*/" in sql:
        raise ValueError("Les commentaires SQL sont interdits.")

    # Retirer les chaînes littérales pour analyser
    # les véritables mots-clés SQL.
    sanitized_sql = remove_sql_string_literals(sql)

    # Refuser les identifiants de tables entre guillemets
    # pour garder une validation simple et prévisible.
    # Les guillemets simples des valeurs SQL restent autorisés.
    if '"' in sanitized_sql or "`" in sanitized_sql:
        raise ValueError("Les identifiants SQL entre guillemets sont interdits.")

    # Autoriser uniquement SELECT au début.
    if not re.match(
        r"^SELECT\b",
        sanitized_sql,
        re.IGNORECASE
    ):
        raise ValueError("Seules les requêtes SELECT sont autorisées.")

    # Interdire les sous-requêtes, CTE et requêtes combinées.
    if len(
        re.findall(r"\bSELECT\b", sanitized_sql, re.IGNORECASE)
    ) != 1:
        raise ValueError("Les sous-requêtes SELECT sont interdites.")

    forbidden_keywords = [
        "INSERT", "UPDATE", "DELETE", "DROP",
        "ALTER", "CREATE", "ATTACH", "DETACH",
        "COPY", "INSTALL", "LOAD", "EXPORT",
        "IMPORT", "CALL", "EXECUTE", "PRAGMA",
        "SET", "RESET", "TRUNCATE", "REPLACE",
        "MERGE", "VACUUM", "ANALYZE",
        "READ_CSV", "READ_CSV_AUTO",
        "READ_PARQUET", "READ_JSON",
        "READ_JSON_AUTO", "READ_TEXT",
        "QUERY"
    ]

    for keyword in forbidden_keywords:

        pattern = rf"\b{keyword}\b"

        if re.search(
            pattern,
            sanitized_sql,
            re.IGNORECASE
        ):
            raise ValueError(
                f"Instruction ou fonction interdite : {keyword}"
            )

    # Détecter les tables utilisées après FROM et JOIN.
    table_references = re.findall(
        r"\b(?:FROM|JOIN)\s+([^\s,()]+)",
        sanitized_sql,
        re.IGNORECASE
    )

    if not table_references:
        raise ValueError("La requête doit utiliser une table autorisée.")

    for table in table_references:

        if table.lower() not in ALLOWED_TABLES:
            raise ValueError(f"Table non autorisée : {table}")

    # Interdire les listes de tables séparées par des virgules.
    if has_top_level_from_comma(sanitized_sql):
        raise ValueError(
            "Les tables séparées par des virgules dans FROM sont interdites."
        )

    return sql




def analyze_sql_results(data):
    """
    Analyse déterministe des résultats SQL.

    Python calcule les statistiques et les classements.
    Aucune conclusion numérique n'est confiée au LLM.
    """

    import pandas as pd

    if data is None:
        return {
            "status": "no_data",
            "message": "Aucun résultat SQL disponible."
        }

    if not isinstance(data, pd.DataFrame):
        raise TypeError("Les résultats doivent être un DataFrame Pandas.")

    if data.empty:
        return {
            "status": "empty",
            "total_rows": 0,
            "message": "La requête n'a retourné aucune ligne."
        }

    analysis = {
        "status": "success",
        "total_rows": len(data),
        "columns": list(data.columns),
        "statistics": {},
        "trend": None,
        "ranking": None,
        "warnings": []
    }

    # 1. Identifier les colonnes numériques.
    numeric_columns = data.select_dtypes(
        include="number"
    ).columns.tolist()

    for column in numeric_columns:

        values = pd.to_numeric(
            data[column],
            errors="coerce"
        ).dropna()

        if values.empty:
            continue

        analysis["statistics"][column] = {
            "minimum": float(values.min()),
            "maximum": float(values.max()),
            "mean": float(values.mean()),
            "median": float(values.median()),
            "count": int(values.count()),
            "missing": int(data[column].isna().sum())
        }

    # 2. Identifier les colonnes temporelles.
    date_candidates = [
        column for column in data.columns
        if any(
            word in column.lower()
            for word in ["date", "mois", "month", "annee", "year"]
        )
    ]

    # 3. Détecter une évolution uniquement si
    # une seule colonne temporelle et une seule
    # colonne numérique sont disponibles.
    if len(date_candidates) == 1 and len(numeric_columns) == 1:

        date_column = date_candidates[0]
        value_column = numeric_columns[0]

        ordered_data = data[[date_column, value_column]].copy()

        ordered_data[date_column] = pd.to_datetime(
            ordered_data[date_column],
            errors="coerce"
        )

        ordered_data[value_column] = pd.to_numeric(
            ordered_data[value_column],
            errors="coerce"
        )

        invalid_dates = int(ordered_data[date_column].isna().sum())

        invalid_values = int(ordered_data[value_column].isna().sum())

        ordered_data = ordered_data.dropna(
            subset=[date_column, value_column]
        ).sort_values(date_column)

        if invalid_dates or invalid_values:
            analysis["warnings"].append(
                "Certaines lignes ont été ignorées à cause de valeurs invalides."
            )

        if len(ordered_data) >= 2:

            first = ordered_data.iloc[0]
            last = ordered_data.iloc[-1]

            first_value = float(first[value_column])
            last_value = float(last[value_column])

            difference = last_value - first_value

            percentage = (
                difference / first_value * 100
                if first_value != 0 else None
            )

            minimum_row = ordered_data.loc[
                ordered_data[value_column].idxmin()
            ]

            maximum_row = ordered_data.loc[
                ordered_data[value_column].idxmax()
            ]

            
            analysis["trend"] = {
                "date_column": date_column,
                "value_column": value_column,
                "first_date": str(first[date_column]),
                "first_value": first_value,
                "last_date": str(last[date_column]),
                "last_value": last_value,
                "difference": difference,
                "percentage_change": percentage,
                "direction": (
                    "hausse" if difference > 0
                    else "baisse" if difference < 0
                    else "stable"
                ),
                "minimum_date": str(minimum_row[date_column]),
                "minimum_value": float(minimum_row[value_column]),
                "maximum_date": str(maximum_row[date_column]),
                "maximum_value": float(maximum_row[value_column])
            }

            # Calcul des variations entre les périodes successives.
            variations = ordered_data[
                [date_column, value_column]
            ].copy()

            variations["variation"] = (
                variations[value_column].diff()
            )

            valid_variations = variations.dropna(
                subset=["variation"]
            )

            hausses = valid_variations[
                valid_variations["variation"] > 0
            ]

            baisses = valid_variations[
                valid_variations["variation"] < 0
            ]

            stabilites = valid_variations[
                valid_variations["variation"] == 0
            ]

            plus_forte_hausse = None
            plus_forte_baisse = None

            if not hausses.empty:
                row = hausses.loc[
                    hausses["variation"].idxmax()
                ]

                plus_forte_hausse = {
                    "date": str(row[date_column]),
                    "variation": float(row["variation"])
                }

            if not baisses.empty:
                row = baisses.loc[
                    baisses["variation"].idxmin()
                ]

                plus_forte_baisse = {
                    "date": str(row[date_column]),
                    "variation": float(row["variation"])
                }

            analysis["trend"].update({
                "nombre_hausses": int(len(hausses)),
                "nombre_baisses": int(len(baisses)),
                "nombre_stabilites": int(len(stabilites)),
                "plus_forte_hausse": plus_forte_hausse,
                "plus_forte_baisse": plus_forte_baisse
            })

    elif len(numeric_columns) > 1:
        analysis["warnings"].append(
            "Plusieurs colonnes numériques détectées : "
            "aucune tendance automatique n'a été calculée."
        )


    # 4. Détecter un classement uniquement lorsqu'une
    # seule colonne numérique et une seule catégorie
    # sont disponibles.
    category_columns = [
        column for column in data.columns
        if column not in numeric_columns
        and column not in date_candidates
    ]

    if len(numeric_columns) == 1 and len(category_columns) == 1:

        value_column = numeric_columns[0]
        category_column = category_columns[0]

        ranking_data = data[
            [category_column, value_column]
        ].copy()

        ranking_data[value_column] = pd.to_numeric(
            ranking_data[value_column],
            errors="coerce"
        )

        ranking_data = ranking_data.dropna(
            subset=[value_column, category_column]
        )

        if not ranking_data.empty:

            minimum_value = ranking_data[value_column].min()
            maximum_value = ranking_data[value_column].max()

            analysis["ranking"] = {
                "category_column": category_column,
                "value_column": value_column,
                "minimum": ranking_data[
                    ranking_data[value_column] == minimum_value
                ].to_dict(orient="records"),
                "maximum": ranking_data[
                    ranking_data[value_column] == maximum_value
                ].to_dict(orient="records")
            }

    return analysis





def generate_answer(question, sql, explanation, data):
    """
    Génère une réponse en français à partir des résultats SQL.

    Python effectue les calculs numériques.
    Qwen interprète les résultats sans modifier les statistiques.
    """

    if data is None:
        raise ValueError("Aucun résultat SQL à interpréter.")

    if not isinstance(data, pd.DataFrame):
        raise TypeError("Les résultats doivent être un DataFrame Pandas.")

    # 1. Gérer directement les résultats vides.
    if data.empty:
        return (
            "La requête SQL a été exécutée correctement, "
            "mais aucune donnée ne correspond à votre demande."
        )

    # 2. Analyse déterministe avec Python.
    analysis = analyze_sql_results(data)

    
    # 2.1. Interprétation déterministe des évolutions temporelles.
    # On évite ainsi les erreurs numériques de Qwen.

    if analysis["trend"] is not None:

        trend = analysis["trend"]

        mois_francais = [
            "janvier", "février", "mars", "avril",
            "mai", "juin", "juillet", "août",
            "septembre", "octobre", "novembre", "décembre"
        ]

        def formater_periode(date_value):
            date = pd.to_datetime(date_value)
            return f"{mois_francais[date.month - 1]} {date.year}"

        premiere_periode = formater_periode(trend["first_date"])
        derniere_periode = formater_periode(trend["last_date"])

        periode_minimum = formater_periode(trend["minimum_date"])
        periode_maximum = formater_periode(trend["maximum_date"])

        difference = trend["difference"]
        pourcentage = trend["percentage_change"]

        direction = trend["direction"]

        if direction == "baisse":
            conclusion = "a diminué"
        elif direction == "hausse":
            conclusion = "a augmenté"
        else:
            conclusion = "est resté stable"

        answer = (
            f"Évolution du prix moyen entre {premiere_periode} "
            f"et {derniere_periode} :\n\n"
            f"Le prix moyen {conclusion}, passant de "
            f"{trend['first_value']:.6f} € à "
            f"{trend['last_value']:.6f} €.\n"
            f"La différence totale est de {difference:+.6f} €, "
        )

        if pourcentage is not None:
            answer += f"soit {pourcentage:+.2f} %.\n\n"
        else:
            answer += "le pourcentage d'évolution n'est pas calculable.\n\n"

        answer += (
            "Variations mensuelles :\n"
            f"- Hausses : {trend['nombre_hausses']}\n"
            f"- Baisses : {trend['nombre_baisses']}\n"
            f"- Stabilités : {trend['nombre_stabilites']}\n\n"
            "Valeurs extrêmes :\n"
            f"- Maximum : {trend['maximum_value']:.6f} € "
            f"en {periode_maximum}\n"
            f"- Minimum : {trend['minimum_value']:.6f} € "
            f"en {periode_minimum}\n"
        )

        hausse = trend["plus_forte_hausse"]
        baisse = trend["plus_forte_baisse"]

        if hausse is not None:
            answer += (
                "\nPlus forte hausse : "
                f"+{hausse['variation']:.6f} € en "
                f"{formater_periode(hausse['date'])}.\n"
            )

        if baisse is not None:
            answer += (
                "Plus forte baisse : "
                f"{baisse['variation']:.6f} € en "
                f"{formater_periode(baisse['date'])}.\n"
            )

        if (
            trend["nombre_hausses"] > 0
            and trend["nombre_baisses"] > 0
        ):
            answer += (
                "\nConclusion : l'évolution est fluctuante. "
                "La baisse globale ne signifie pas que le prix "
                "a diminué continuellement."
            )

        return answer


    # 3. Préparer l'aperçu des résultats.
    preview = data.head(MAX_PREVIEW_ROWS)

    records = preview.to_dict(orient="records")

    preview_json = json.dumps(
        records,
        ensure_ascii=False,
        default=str
    )

    analysis_json = json.dumps(
        analysis,
        ensure_ascii=False,
        default=str,
        indent=2
    )

    total_rows = len(data)
    displayed_rows = len(preview)

    # 4. Construire les instructions d'interprétation.
    system_prompt = """
Tu es DataPilot AI, un assistant spécialisé
dans l'analyse et l'interprétation des données.

Tu dois répondre clairement et exclusivement en français.

==================================================
REGLES OBLIGATOIRES
==================================================

1. FIABILITE DES CALCULS

Les statistiques calculées par Python constituent
la référence numérique officielle.

Tu ne dois jamais recalculer ni modifier :
- les minimums ;
- les maximums ;
- les moyennes ;
- les différences ;
- les pourcentages ;
- les nombres de hausses et de baisses.

2. EVOLUTION GLOBALE

Distingue obligatoirement :
- l'évolution entre la première et la dernière période ;
- les variations entre les périodes successives.

La direction globale ne signifie pas que toutes
les périodes ont évolué dans la même direction.

3. VARIATIONS MENSUELLES

Si l'analyse Python fournit :
- nombre_hausses ;
- nombre_baisses ;
- nombre_stabilites ;

utilise ces informations pour décrire les variations.

Règles impératives :

- Si le nombre de hausses est supérieur à zéro
  ET le nombre de baisses est supérieur à zéro,
  décris une évolution fluctuante.

- Si le nombre de hausses est supérieur à zéro,
  tu ne dois jamais affirmer que le prix a diminué
  continuellement.

- Si le nombre de baisses est supérieur à zéro,
  tu ne dois jamais affirmer que le prix a augmenté
  continuellement.

- Si toutes les variations sont des baisses,
  tu peux parler d'une baisse continue sur les périodes
  effectivement analysées.

- Si toutes les variations sont des hausses,
  tu peux parler d'une hausse continue sur les périodes
  effectivement analysées.

- Si des stabilités existent, mentionne-les lorsque
  cela apporte une information utile.

4. PLUS FORTES VARIATIONS

Si elles sont disponibles, mentionne :
- la plus forte hausse et sa période ;
- la plus forte baisse et sa période.

Utilise exactement les valeurs calculées par Python.

5. INTERDICTION D'INVENTER

- N'invente aucun chiffre.
- Ne crée aucune période absente des résultats.
- Ne déduis aucune causalité sans preuve.
- Ne contredis jamais les statistiques Python.
- Si une information est indisponible, indique-le.

6. APERCU DES DONNEES

L'aperçu peut être limité à 20 lignes.

Ne prétends jamais que cet aperçu représente
l'intégralité des données lorsque le nombre total
de lignes est supérieur au nombre affiché.

7. PRESENTATION

Réponds directement à la question.
Utilise des phrases simples et compréhensibles.
Organise la réponse en paragraphes ou en puces
lorsque cela facilite la lecture.
Évite les répétitions.
"""

    # 5. Construire le contexte envoyé à Qwen.
    user_prompt = f"""
QUESTION DE L'UTILISATEUR :
{question}

REQUETE SQL EXECUTEE :
{sql}

OBJECTIF DE LA REQUETE :
{explanation}

NOMBRE TOTAL DE LIGNES :
{total_rows}

NOMBRE DE LIGNES DANS L'APERÇU :
{displayed_rows}

APERÇU DES RESULTATS :
{preview_json}

ANALYSE NUMERIQUE CALCULEE PAR PYTHON :
{analysis_json}

==================================================
MISSION
==================================================

Réponds directement à la question de l'utilisateur.

Si une évolution temporelle est disponible :

1. Présente la direction globale entre la première
   et la dernière période.

2. Présente le nombre de hausses, de baisses
   et de stabilités.

3. Décris correctement les fluctuations intermédiaires.

4. Mentionne les plus fortes variations si elles
   sont disponibles.

5. Ne confonds jamais une baisse globale avec
   une baisse continue.

Les données et statistiques Python sont prioritaires.
Ne modifie aucune valeur.
"""

    response = ollama.chat(
        model=MODEL,
        messages=[
            {
                "role": "system",
                "content": system_prompt
            },
            {
                "role": "user",
                "content": user_prompt
            }
        ],
        options={
            "temperature": 0
        }
    )

    # 6. Vérifier la réponse de Qwen.
    try:
        answer = response["message"]["content"].strip()

        if not answer:
            raise ValueError("Réponse vide de Qwen.")

        return answer

    except (KeyError, TypeError):
        raise ValueError(
            "Qwen n'a pas fourni de réponse interprétable."
        )




def run_agent():

    print("\n" + "=" * 60)
    print("             DATAPILOT AI - AGENT SQL")
    print("=" * 60)

    engine = QueryEngine()

    try:

        while True:

            question = input(
                "\nPosez votre question (ou 'exit' pour quitter) : "
            ).strip()

            if question.lower() in ["exit", "quit", "q"]:
                print("\nFermeture de DataPilot AI.")
                break

            if not question:
                print("Veuillez saisir une question.")
                continue

            try:

                # 1. Génération initiale du SQL.
                print("\n[1] Génération de la requête SQL...")

                sql, explanation = generate_sql(question)

                result = None

                # 2. Exécution avec trois tentatives maximum.
                for attempt in range(1, MAX_ATTEMPTS + 1):

                    print(f"\n--- Tentative {attempt}/{MAX_ATTEMPTS} ---")
                    print("\nRequête SQL :")
                    print(sql)

                    try:

                        # Validation de sécurité.
                        validated_sql = validate_sql(sql)

                        # Exécution avec QueryEngine.
                        result = engine.execute_query(validated_sql)

                        # Garder la requête réellement exécutée.
                        sql = validated_sql

                        print("\nRequête exécutée avec succès !")
                        break

                    except Exception as error:

                        print(f"\nErreur : {error}")

                        if attempt == MAX_ATTEMPTS:

                            print(
                                "\nÉchec : nombre maximum de tentatives atteint."
                            )
                            break

                        # 3. Correction automatique par Qwen.
                        sql, explanation = correct_sql(
                            question,
                            sql,
                            str(error)
                        )

                # 4. Vérifier le résultat.
                if result is None:

                    print("\nImpossible d'obtenir un résultat.")
                    continue

                print("\nExplication de la requête :")
                print(explanation)

                print("\nRésultat :")
                print(result.head(20).to_string(index=False))

                print(f"\nNombre total de lignes : {len(result)}")

                # 5. Génération d'une réponse en langage naturel.
                print("\nAnalyse du résultat par Qwen...")

                answer = generate_answer(
                    question,
                    sql,
                    explanation,
                    result
                )

                print("\nRéponse de DataPilot AI :")
                print(answer)

            except Exception as error:

                print(f"\nUne erreur est survenue : {error}")

    finally:

        engine.close()
        print("\nConnexion à DuckDB fermée.")


if __name__ == "__main__":
    run_agent()
