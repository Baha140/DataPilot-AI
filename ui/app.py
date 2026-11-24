
from pathlib import Path
from datetime import datetime

import duckdb
import streamlit as st
import pandas as pd
import plotly.express as px

from datapilot.agent import orchestrator


# ============================================================
# CONFIGURATION
# ============================================================

st.set_page_config(
    page_title="DataPilot AI",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded"
)

DB_PATH = orchestrator.DB_PATH


# ============================================================
# STYLE CSS
# ============================================================

st.markdown("""
<style>
    .stApp {
        background-color: #F5F7FB;
    }

    [data-testid="stSidebar"] {
        background-color: #172554;
    }

    [data-testid="stSidebar"] * {
        color: white;
    }

    .main-title {
        font-size: 32px;
        font-weight: 800;
        color: #172554;
        margin-bottom: 5px;
    }

    .subtitle {
        color: #64748B;
        font-size: 15px;
        margin-bottom: 25px;
    }

    div[data-testid="stMetric"] {
        background-color: white;
        padding: 20px;
        border-radius: 12px;
        border: 1px solid #E2E8F0;
    }
</style>
""", unsafe_allow_html=True)


# ============================================================
# CONNEXION DUCKDB
# ============================================================

def get_connection():

    if not DB_PATH.exists():
        raise FileNotFoundError(
            f"Base de données introuvable : {DB_PATH}"
        )

    return duckdb.connect(str(DB_PATH), read_only=True)


# ============================================================
# OUTIL DE FORMATAGE
# ============================================================

def format_number(value):
    return f"{int(value):,}".replace(",", " ")


# ============================================================
# DONNEES DU TABLEAU DE BORD
# ============================================================

@st.cache_data(ttl=300)
def get_dashboard_data():

    con = get_connection()

    # Indicateurs généraux
    stations = con.execute(
        "SELECT COUNT(*) FROM stations"
    ).fetchone()[0]

    prix = con.execute(
        "SELECT COUNT(*) FROM prix"
    ).fetchone()[0]

    ruptures = con.execute(
        "SELECT COUNT(*) FROM ruptures"
    ).fetchone()[0]

    carburants = con.execute("""
        SELECT COUNT(DISTINCT carburant)
        FROM prix
        WHERE carburant IS NOT NULL
    """).fetchone()[0]

    # Qualité des prix
    prix_manquants = con.execute("""
        SELECT COUNT(*)
        FROM prix
        WHERE prix IS NULL
    """).fetchone()[0]

    prix_invalides = con.execute("""
        SELECT COUNT(*)
        FROM prix
        WHERE prix IS NOT NULL
          AND prix <= 0
    """).fetchone()[0]

    # Prix moyens par carburant
    prix_par_carburant = con.execute("""
        SELECT
            carburant,
            COUNT(*) AS nombre_prix,
            ROUND(AVG(prix), 3) AS prix_moyen
        FROM prix
        WHERE carburant IS NOT NULL
          AND prix IS NOT NULL
          AND prix > 0
        GROUP BY carburant
        ORDER BY prix_moyen DESC
    """).df()

    # Evolution mensuelle des prix
    evolution_mensuelle = con.execute("""
        SELECT
            DATE_TRUNC('month', date_maj) AS mois,
            carburant,
            ROUND(AVG(prix), 3) AS prix_moyen
        FROM prix
        WHERE date_maj IS NOT NULL
          AND carburant IS NOT NULL
          AND prix IS NOT NULL
          AND prix > 0
        GROUP BY
            DATE_TRUNC('month', date_maj),
            carburant
        ORDER BY mois
    """).df()

    # Derniers enregistrements
    derniers_prix = con.execute("""
        SELECT
            station_id,
            carburant,
            date_maj,
            prix
        FROM prix
        ORDER BY date_maj DESC
        LIMIT 10
    """).df()

    # Comparaison des tables originales et nettoyées
    tables = [
        ("Stations", "stations", "stations_clean"),
        ("Prix", "prix", "prix_clean"),
        ("Ruptures", "ruptures", "ruptures_clean")
    ]

    etat_donnees = []

    for nom, table_originale, table_clean in tables:

        nombre_original = con.execute(
            f"SELECT COUNT(*) FROM {table_originale}"
        ).fetchone()[0]

        nombre_clean = con.execute(
            f"SELECT COUNT(*) FROM {table_clean}"
        ).fetchone()[0]

        etat_donnees.append({
            "Type de données": nom,
            "Table originale": table_originale,
            "Lignes originales": nombre_original,
            "Table nettoyée": table_clean,
            "Lignes nettoyées": nombre_clean
        })

    con.close()

    return {
        "stations": stations,
        "prix": prix,
        "ruptures": ruptures,
        "carburants": carburants,
        "prix_manquants": prix_manquants,
        "prix_invalides": prix_invalides,
        "prix_par_carburant": prix_par_carburant,
        "evolution_mensuelle": evolution_mensuelle,
        "derniers_prix": derniers_prix,
        "etat_donnees": pd.DataFrame(etat_donnees)
    }


# ============================================================
# ANALYSE DE QUALITE
# ============================================================

@st.cache_data(ttl=300)
def get_quality_data():

    return orchestrator.execute_quality()


# ============================================================
# SIDEBAR
# ============================================================

with st.sidebar:

    st.markdown("# 📊 DataPilot AI")
    st.caption("Autonomous Data Analysis Agent")

    st.divider()

    page = st.radio(
        "NAVIGATION",
        [
            "Tableau de bord",
            "Importation des données",
            "Diagnostic",
            "Nettoyage",
            "Assistant IA",
            "Analyses",
            "Rapports"
        ]
    )

    st.divider()

    if st.button("Actualiser les données", width="stretch"):
        st.cache_data.clear()
        st.rerun()

    st.divider()

    st.caption("Version 1.0")
    st.caption("Powered by DuckDB & Qwen")


# ============================================================
# TABLEAU DE BORD
# ============================================================

if page == "Tableau de bord":

    st.markdown(
        '<div class="main-title">Tableau de bord</div>',
        unsafe_allow_html=True
    )

    st.markdown(
        '<div class="subtitle">'
        'Vue générale de votre environnement de données'
        '</div>',
        unsafe_allow_html=True
    )

    try:

        data = get_dashboard_data()

        # ----------------------------------------------------
        # INDICATEURS GENERAUX
        # ----------------------------------------------------

        st.subheader("Vue générale")

        col1, col2, col3, col4 = st.columns(4)

        col1.metric(
            "Stations",
            format_number(data["stations"])
        )

        col2.metric(
            "Enregistrements de prix",
            format_number(data["prix"])
        )

        col3.metric(
            "Ruptures",
            format_number(data["ruptures"])
        )

        col4.metric(
            "Carburants",
            data["carburants"]
        )

        st.divider()

        # ----------------------------------------------------
        # INDICATEURS QUALITE
        # ----------------------------------------------------

        st.subheader("Qualité des données")

        quality = get_quality_data()

        nombre_anomalies = quality.get(
            "nombre_total_anomalies", 0
        )

        col1, col2, col3 = st.columns(3)

        col1.metric(
            "Prix manquants",
            format_number(data["prix_manquants"])
        )

        col2.metric(
            "Prix invalides",
            format_number(data["prix_invalides"])
        )

        col3.metric(
            "Anomalies statistiques",
            format_number(nombre_anomalies)
        )

        st.caption(
            "Les anomalies statistiques sont des valeurs atypiques "
            "détectées par la méthode IQR. Elles ne sont pas "
            "nécessairement des erreurs."
        )

        anomalies = quality.get("anomalies_prix")

        if isinstance(anomalies, pd.DataFrame) and not anomalies.empty:

            with st.expander("Détails des anomalies par carburant"):

                st.dataframe(
                    anomalies,
                    width="stretch",
                    hide_index=True
                )

        st.divider()

        # ----------------------------------------------------
        # PRIX MOYENS PAR CARBURANT
        # ----------------------------------------------------

        st.subheader("Prix moyen par carburant")

        df_prix = data["prix_par_carburant"]

        fig_prix = px.bar(
            df_prix,
            x="carburant",
            y="prix_moyen",
            color="carburant",
            text="prix_moyen",
            hover_data=["nombre_prix"],
            labels={
                "carburant": "Carburant",
                "prix_moyen": "Prix moyen (€ / litre)",
                "nombre_prix": "Nombre de prix"
            }
        )

        fig_prix.update_traces(
            texttemplate="%{text:.3f} €",
            textposition="outside"
        )

        fig_prix.update_layout(
            template="plotly_white",
            showlegend=False,
            height=420,
            margin=dict(l=20, r=20, t=30, b=20)
        )

        st.plotly_chart(
            fig_prix,
            width="stretch"
        )

        st.divider()

        # ----------------------------------------------------
        # EVOLUTION MENSUELLE
        # ----------------------------------------------------

        st.subheader("Évolution mensuelle des prix")

        df_mois = data["evolution_mensuelle"]

        if not df_mois.empty:

            carburants_disponibles = sorted(
                df_mois["carburant"].dropna().unique().tolist()
            )

            carburants_selectionnes = st.multiselect(
                "Sélectionner les carburants",
                options=carburants_disponibles,
                default=carburants_disponibles
            )

            df_filtre = df_mois[
                df_mois["carburant"].isin(carburants_selectionnes)
            ]

            if not df_filtre.empty:

                fig_mois = px.line(
                    df_filtre,
                    x="mois",
                    y="prix_moyen",
                    color="carburant",
                    markers=True,
                    labels={
                        "mois": "Mois",
                        "prix_moyen": "Prix moyen (€ / litre)",
                        "carburant": "Carburant"
                    }
                )

                fig_mois.update_layout(
                    template="plotly_white",
                    height=450,
                    hovermode="x unified"
                )

                st.plotly_chart(
                    fig_mois,
                    width="stretch"
                )

            else:
                st.info(
                    "Sélectionnez au moins un carburant."
                )

        else:
            st.info(
                "Aucune donnée mensuelle disponible."
            )

        st.divider()

        # ----------------------------------------------------
        # ETAT DES DONNEES
        # ----------------------------------------------------

        st.subheader("État des données")

        st.dataframe(
            data["etat_donnees"],
            width="stretch",
            hide_index=True
        )

        st.divider()

        # ----------------------------------------------------
        # DERNIERS ENREGISTREMENTS
        # ----------------------------------------------------

        st.subheader("Derniers enregistrements de prix")

        st.dataframe(
            data["derniers_prix"],
            width="stretch",
            hide_index=True
        )

    except Exception as error:

        st.error(
            f"Impossible de charger le tableau de bord : {error}"
        )


# ============================================================
# AUTRES PAGES
# ============================================================


elif page == "Diagnostic":

    st.markdown(
        '<div class="main-title">Diagnostic des données</div>',
        unsafe_allow_html=True
    )

    st.markdown(
        '<div class="subtitle">'
        'Analysez la structure et la qualité de vos tables.'
        '</div>',
        unsafe_allow_html=True
    )

    # Sélection de la table
    choix_table = st.selectbox(
        "Sélectionner une table",
        [
            "stations",
            "prix",
            "ruptures",
            "Toutes les tables"
        ]
    )

    table_a_diagnostiquer = (
        "all" if choix_table == "Toutes les tables"
        else choix_table
    )

    # Lancement du diagnostic
    if st.button("Lancer le diagnostic", type="primary"):

        try:
            with st.spinner(
                "Analyse des données en cours... Cela peut prendre un moment."
            ):
                resultats = orchestrator.execute_diagnostic(
                    table_a_diagnostiquer
                )

            st.session_state["diagnostic_results"] = resultats
            st.session_state["diagnostic_selection"] = choix_table

            st.success("Diagnostic terminé avec succès.")

        except Exception as error:
            st.error(f"Erreur pendant le diagnostic : {error}")

    # Affichage des résultats
    resultats = st.session_state.get("diagnostic_results")

    if resultats:

        st.divider()

        st.subheader("Résultats du diagnostic")

        for nom_table, resultat in resultats.items():

            with st.expander(
                f"Diagnostic : {nom_table.upper()}",
                expanded=True
            ):

                # Données générales
                total_lignes = resultat["total_rows"]
                total_colonnes = resultat["total_columns"]
                doublons = resultat["duplicate_groups"]

                # Récupération des valeurs manquantes
                missing_data = resultat["missing_values"]

                if missing_data:
                    missing_dict = missing_data[0]
                else:
                    missing_dict = {}

                nombre_manquants = sum(
                    int(value or 0)
                    for value in missing_dict.values()
                )

                # Indicateurs
                col1, col2, col3, col4 = st.columns(4)

                col1.metric(
                    "Nombre de lignes",
                    format_number(total_lignes)
                )

                col2.metric(
                    "Nombre de colonnes",
                    format_number(total_colonnes)
                )

                col3.metric(
                    "Valeurs manquantes",
                    format_number(nombre_manquants)
                )

                col4.metric(
                    "Groupes dupliqués",
                    format_number(doublons)
                )

                st.divider()

                # Types des colonnes
                st.markdown("#### Types des colonnes")

                df_types = pd.DataFrame(
                    resultat["column_types"]
                )

                df_types.columns = [
                    "Colonne",
                    "Type de données"
                ]

                st.dataframe(
                    df_types,
                    width="stretch",
                    hide_index=True
                )

                # Valeurs manquantes
                st.markdown("#### Valeurs manquantes par colonne")

                lignes_manquantes = []

                for colonne, count in missing_dict.items():

                    pourcentage = (
                        count / total_lignes * 100
                        if total_lignes else 0
                    )

                    lignes_manquantes.append({
                        "Colonne": colonne,
                        "Valeurs manquantes": count,
                        "Pourcentage (%)": round(pourcentage, 2)
                    })

                df_manquantes = pd.DataFrame(
                    lignes_manquantes
                )

                st.dataframe(
                    df_manquantes,
                    width="stretch",
                    hide_index=True
                )

                # Graphique des valeurs manquantes
                df_graphique = df_manquantes[
                    df_manquantes["Valeurs manquantes"] > 0
                ]

                if not df_graphique.empty:

                    fig_missing = px.bar(
                        df_graphique,
                        x="Colonne",
                        y="Valeurs manquantes",
                        text="Valeurs manquantes",
                        color="Valeurs manquantes",
                        labels={
                            "Colonne": "Colonne",
                            "Valeurs manquantes": "Nombre de valeurs manquantes"
                        }
                    )

                    fig_missing.update_layout(
                        template="plotly_white",
                        showlegend=False,
                        height=350
                    )

                    st.plotly_chart(
                        fig_missing,
                        width="stretch"
                    )

                else:
                    st.success(
                        "Aucune valeur manquante détectée."
                    )

                # Doublons
                st.markdown("#### Doublons")

                if doublons > 0:
                    st.warning(
                        f"{format_number(doublons)} groupes de lignes "
                        "dupliquées détectés."
                    )
                else:
                    st.success(
                        "Aucun groupe de lignes dupliquées détecté."
                    )

                # Aperçu des données
                st.markdown("#### Aperçu des données")

                df_sample = pd.DataFrame(
                    resultat["sample"]
                )

                st.dataframe(
                    df_sample,
                    width="stretch",
                    hide_index=True
                )

    else:
        st.info(
            "Sélectionnez une table puis cliquez sur "
            "'Lancer le diagnostic' pour commencer."
        )


elif page == "Nettoyage":

    st.markdown(
        '<div class="main-title">Nettoyage des données</div>',
        unsafe_allow_html=True
    )

    st.markdown(
        '<div class="subtitle">'
        'Normalisation des données et détection des problèmes '
        'sans supprimer les enregistrements originaux.'
        '</div>',
        unsafe_allow_html=True
    )

    st.info(
        "Le nettoyage crée trois tables séparées : "
        "stations_clean, prix_clean et ruptures_clean. "
        "Les tables originales restent intactes."
    )

    # ----------------------------------------------------
    # LANCEMENT DU NETTOYAGE
    # ----------------------------------------------------

    if st.button("Lancer le nettoyage", type="primary"):

        try:
            with st.spinner(
                "Nettoyage des données en cours... "
                "Cette opération peut prendre un moment."
            ):

                resultats = orchestrator.execute_cleaning()

            st.session_state["cleaning_results"] = resultats

            st.success("Nettoyage terminé avec succès.")

            # Actualiser les données du tableau de bord
            st.cache_data.clear()

        except Exception as error:
            st.error(f"Erreur pendant le nettoyage : {error}")

    # ----------------------------------------------------
    # AFFICHAGE DES RESULTATS
    # ----------------------------------------------------

    resultats = st.session_state.get("cleaning_results")

    if resultats:

        st.divider()

        st.subheader("Résultats du nettoyage")

        # Conservation des données
        if resultats.get("conservation_donnees"):

            st.success(
                "Toutes les lignes originales ont été conservées."
            )

        else:

            st.error(
                "Attention : une différence a été détectée "
                "dans le nombre de lignes."
            )

        # ------------------------------------------------
        # TABLES NETTOYEES
        # ------------------------------------------------

        tables = [
            ("Stations", "stations_clean"),
            ("Prix", "prix_clean"),
            ("Ruptures", "ruptures_clean")
        ]

        for nom, cle in tables:

            if cle not in resultats:
                continue

            donnees = resultats[cle]

            with st.expander(
                f"Nettoyage : {nom}",
                expanded=True
            ):

                total = donnees["total_lignes"]
                statuts = donnees["statuts"]
                indicateurs = donnees.get("indicateurs", {})

                # Indicateurs principaux
                col1, col2, col3 = st.columns(3)

                conformes = statuts.get("OK", 0)
                problemes = total - conformes

                if cle == "stations_clean":
                    conformes = statuts.get("A_VERIFIER", 0)
                    problemes = total - conformes

                col1.metric(
                    "Total des lignes",
                    format_number(total)
                )

                col2.metric(
                    "Lignes sans problème signalé",
                    format_number(conformes)
                )

                col3.metric(
                    "Lignes à vérifier",
                    format_number(problemes)
                )

                # Répartition des statuts
                st.markdown("#### Répartition des statuts")

                df_statuts = pd.DataFrame([
                    {
                        "Statut": statut,
                        "Nombre de lignes": nombre
                    }
                    for statut, nombre in statuts.items()
                ])

                st.dataframe(
                    df_statuts,
                    width="stretch",
                    hide_index=True
                )

                if not df_statuts.empty:

                    fig_statuts = px.bar(
                        df_statuts,
                        x="Statut",
                        y="Nombre de lignes",
                        color="Statut",
                        text="Nombre de lignes"
                    )

                    fig_statuts.update_layout(
                        template="plotly_white",
                        showlegend=False,
                        height=350
                    )

                    st.plotly_chart(
                        fig_statuts,
                        width="stretch"
                    )

                # Détail des problèmes
                st.markdown("#### Détail des indicateurs")

                df_indicateurs = pd.DataFrame([
                    {
                        "Indicateur": nom_indicateur.replace("_", " ").capitalize(),
                        "Nombre": nombre
                    }
                    for nom_indicateur, nombre in indicateurs.items()
                ])

                st.dataframe(
                    df_indicateurs,
                    width="stretch",
                    hide_index=True
                )

                # Information particulière sur les ruptures
                if cle == "ruptures_clean":

                    st.caption(
                        "Une date de fin absente n'est pas "
                        "automatiquement une erreur : elle peut "
                        "indiquer une rupture toujours en cours."
                    )

    else:

        st.info(
            "Cliquez sur « Lancer le nettoyage » pour créer "
            "les tables nettoyées et afficher les résultats."
        )



elif page == "Assistant IA":

    st.markdown(
        '<div class="main-title">Assistant IA</div>',
        unsafe_allow_html=True
    )

    st.markdown(
        '<div class="subtitle">Posez vos questions sur vos données. '
        'DataPilot AI analysera votre demande et exécutera les actions nécessaires.</div>',
        unsafe_allow_html=True
    )

    # Initialisation de l'historique
    if "chat_history" not in st.session_state:
        st.session_state["chat_history"] = []

    # Fonction d'affichage des résultats
    def afficher_resultats(resultat):

        action = resultat.get("action")
        status = resultat.get("status")
        data = resultat.get("data")

        st.markdown(f"**Action : {action}**")

        if status == "ECHEC":
            st.error(resultat.get("error", "Une erreur est survenue."))
            return

        st.success("Action exécutée avec succès.")

        # Résultats SQL
        if action == "sql" and isinstance(data, dict):

            st.markdown("#### Interprétation")

            st.write(data.get("interpretation", "Aucune interprétation."))

            st.caption(
                f"Nombre total de lignes : "
                f"{format_number(data.get('nombre_total_lignes', 0))}"
            )

            with st.expander("Afficher la requête SQL"):
                st.code(data.get("requete_sql", ""), language="sql")
                st.write(data.get("explication", ""))

            lignes = data.get("resultats", [])

            if lignes:
                st.markdown("#### Résultats")
                st.dataframe(
                    pd.DataFrame(lignes),
                    width="stretch",
                    hide_index=True
                )

        # Résultats du diagnostic
        elif action == "diagnostic" and isinstance(data, dict):

            for nom_table, info in data.items():

                with st.expander(
                    f"Diagnostic de la table : {nom_table}",
                    expanded=True
                ):

                    col1, col2, col3 = st.columns(3)

                    col1.metric(
                        "Lignes",
                        format_number(info.get("total_rows", 0))
                    )

                    col2.metric(
                        "Colonnes",
                        format_number(info.get("total_columns", 0))
                    )

                    col3.metric(
                        "Groupes dupliqués",
                        format_number(info.get("duplicate_groups", 0))
                    )

                    missing = info.get("missing_values", [])

                    if missing and isinstance(missing[0], dict):
                        df_missing = pd.DataFrame(
                            list(missing[0].items()),
                            columns=["Colonne", "Valeurs manquantes"]
                        )

                        st.markdown("**Valeurs manquantes**")
                        st.dataframe(
                            df_missing,
                            width="stretch",
                            hide_index=True
                        )

                    sample = info.get("sample", [])

                    if sample:
                        st.markdown("**Aperçu des données**")
                        st.dataframe(
                            pd.DataFrame(sample),
                            width="stretch",
                            hide_index=True
                        )

        # Autres actions : qualité, nettoyage et analyse avancée
        else:

            if isinstance(data, dict):
                st.write(data)
            elif data is not None:
                st.write(data)

    # Zone de conversation
    question = st.chat_input(
        "Posez une question sur vos données..."
    )

    if question:

        st.session_state["chat_history"].append({
            "role": "user",
            "content": question
        })

        try:

            with st.spinner(
                "DataPilot AI analyse votre demande..."
            ):

                plan = orchestrator.plan_actions(question)

                if not plan or all(
                    step.get("action") == "unknown"
                    for step in plan
                ):

                    assistant_message = (
                        "Je n'ai pas réussi à identifier précisément "
                        "votre demande. Essayez de reformuler votre question."
                    )

                    results = []

                else:

                    results = orchestrator.execute_plan(
                        plan,
                        question
                    )

                    nombre_reussies = sum(
                        1 for item in results
                        if item.get("status") == "REUSSIE"
                    )

                    nombre_echecs = sum(
                        1 for item in results
                        if item.get("status") == "ECHEC"
                    )

                    assistant_message = (
                        f"J'ai terminé l'exécution de votre demande. "
                        f"{nombre_reussies} action(s) réussie(s) "
                        f"et {nombre_echecs} échec(s)."
                    )

        except Exception as error:

            assistant_message = (
                f"Une erreur est survenue : {str(error)}"
            )

            plan = []
            results = []

        st.session_state["chat_history"].append({
            "role": "assistant",
            "content": assistant_message,
            "plan": plan,
            "results": results
        })

        st.rerun()

    # Affichage de l'historique
    for message in st.session_state["chat_history"]:

        with st.chat_message(message["role"]):

            st.write(message["content"])

            if message["role"] == "assistant":

                plan = message.get("plan", [])

                if plan:
                    with st.expander("Plan d'exécution"):
                        for step in plan:
                            st.write(
                                f"- {step.get('action')} "
                                f"(table : {step.get('table')})"
                            )

                for resultat in message.get("results", []):
                    afficher_resultats(resultat)


elif page == "Analyses":

    st.markdown(
        '<div class="main-title">Analyses statistiques</div>',
        unsafe_allow_html=True
    )

    st.markdown(
        '<div class="subtitle">'
        'Étudiez l’évolution mensuelle des prix et identifiez '
        'les observations statistiquement inhabituelles.'
        '</div>',
        unsafe_allow_html=True
    )

    st.info(
        "Cette analyse utilise les prix valides et calcule les "
        "anomalies statistiques avec la méthode IQR. "
        "Une anomalie statistique n'est pas nécessairement une erreur."
    )

    # ----------------------------------------------------
    # LANCEMENT DE L'ANALYSE
    # ----------------------------------------------------

    if st.button(
        "Lancer l'analyse statistique",
        type="primary"
    ):

        try:

            with st.spinner(
                "Analyse mensuelle en cours... "
                "Cette opération peut prendre un moment."
            ):

                resultats = orchestrator.execute_advanced_analysis()

            st.session_state["advanced_analysis_results"] = resultats

            st.success("Analyse statistique terminée avec succès.")

        except Exception as error:

            st.error(
                f"Erreur pendant l'analyse statistique : {error}"
            )

    # ----------------------------------------------------
    # AFFICHAGE DES RESULTATS
    # ----------------------------------------------------

    resultats = st.session_state.get(
        "advanced_analysis_results"
    )

    if resultats:

        st.divider()

        resume = resultats.get("resume", {})
        qualite = resultats.get("qualite_donnees", {})

        # Conversion en DataFrames
        df_stats = pd.DataFrame(
            resultats.get("statistiques_mensuelles", [])
        )

        df_anomalies = pd.DataFrame(
            resultats.get("anomalies_mensuelles", [])
        )

        df_ruptures = pd.DataFrame(
            resultats.get("ruptures_dates_incoherentes", [])
        )

        # ------------------------------------------------
        # 1. INDICATEURS GENERAUX
        # ------------------------------------------------

        st.subheader("Vue générale de l'analyse")

        col1, col2, col3, col4 = st.columns(4)

        col1.metric(
            "Lignes analysées",
            format_number(
                resume.get("nombre_lignes_analysees", 0)
            )
        )

        col2.metric(
            "Mois analysés",
            format_number(
                resume.get("nombre_mois_analyses", 0)
            )
        )

        col3.metric(
            "Carburants analysés",
            format_number(
                resume.get("nombre_carburants_analyses", 0)
            )
        )

        col4.metric(
            "Anomalies mensuelles",
            format_number(
                resume.get("nombre_total_anomalies_mensuelles", 0)
            )
        )

        col5, col6, col7 = st.columns(3)

        col5.metric(
            "Groupes d'anomalies",
            format_number(
                resume.get("nombre_groupes_anomalies", 0)
            )
        )

        col6.metric(
            "Ruptures incohérentes",
            format_number(
                resume.get("nombre_ruptures_incoherentes", 0)
            )
        )

        col7.metric(
            "Lignes exclues",
            format_number(
                resume.get("nombre_lignes_exclues", 0)
            )
        )

        st.divider()

        # ------------------------------------------------
        # 2. QUALITE DES DONNEES ANALYSEES
        # ------------------------------------------------

        st.subheader("Qualité des données utilisées")

        col1, col2, col3, col4 = st.columns(4)

        col1.metric(
            "Total des enregistrements",
            format_number(
                qualite.get("total_lignes", 0)
            )
        )

        col2.metric(
            "Prix analysés",
            format_number(
                qualite.get("lignes_analysees", 0)
            )
        )

        col3.metric(
            "Prix manquants",
            format_number(
                qualite.get("prix_manquants", 0)
            )
        )

        col4.metric(
            "Lignes exclues",
            format_number(
                qualite.get("lignes_exclues", 0)
            )
        )

        with st.expander("Détails des exclusions"):

            df_qualite = pd.DataFrame([
                {
                    "Indicateur": "Prix manquants",
                    "Nombre": qualite.get("prix_manquants", 0)
                },
                {
                    "Indicateur": "Prix non positifs",
                    "Nombre": qualite.get("prix_non_positifs", 0)
                },
                {
                    "Indicateur": "Carburants manquants",
                    "Nombre": qualite.get("carburants_manquants", 0)
                },
                {
                    "Indicateur": "Dates manquantes",
                    "Nombre": qualite.get("dates_manquantes", 0)
                },
                {
                    "Indicateur": "Lignes exclues",
                    "Nombre": qualite.get("lignes_exclues", 0)
                }
            ])

            st.dataframe(
                df_qualite,
                width="stretch",
                hide_index=True
            )

        st.divider()

        # ------------------------------------------------
        # 3. FILTRES
        # ------------------------------------------------

        st.subheader("Filtres d'analyse")

        carburants_disponibles = []

        if not df_stats.empty and "carburant" in df_stats.columns:

            carburants_disponibles = sorted(
                df_stats["carburant"].dropna().unique().tolist()
            )

        carburants_selectionnes = st.multiselect(
            "Sélectionner les carburants",
            options=carburants_disponibles,
            default=carburants_disponibles,
            key="analyse_carburants"
        )

        if not carburants_selectionnes:

            st.warning(
                "Sélectionnez au moins un carburant pour afficher "
                "les analyses."
            )

        else:

            # Filtrage des statistiques
            if not df_stats.empty and "carburant" in df_stats.columns:

                df_stats_filtre = df_stats[
                    df_stats["carburant"].isin(
                        carburants_selectionnes
                    )
                ].copy()

            else:
                df_stats_filtre = pd.DataFrame()

            # Filtrage des anomalies
            if not df_anomalies.empty and "carburant" in df_anomalies.columns:

                df_anomalies_filtre = df_anomalies[
                    df_anomalies["carburant"].isin(
                        carburants_selectionnes
                    )
                ].copy()

            else:
                df_anomalies_filtre = pd.DataFrame()

            # Conversion des dates
            if not df_stats_filtre.empty and "mois" in df_stats_filtre.columns:

                df_stats_filtre["mois"] = pd.to_datetime(
                    df_stats_filtre["mois"],
                    errors="coerce"
                )

            if not df_anomalies_filtre.empty and "mois" in df_anomalies_filtre.columns:

                df_anomalies_filtre["mois"] = pd.to_datetime(
                    df_anomalies_filtre["mois"],
                    errors="coerce"
                )

            # ------------------------------------------------
            # 4. EVOLUTION MENSUELLE DES PRIX
            # ------------------------------------------------

            st.divider()

            st.subheader("Évolution mensuelle des prix")

            if (
                not df_stats_filtre.empty
                and {"mois", "carburant", "prix_moyen"}.issubset(
                    df_stats_filtre.columns
                )
            ):

                fig_evolution = px.line(
                    df_stats_filtre,
                    x="mois",
                    y="prix_moyen",
                    color="carburant",
                    markers=True,
                    hover_data=["nombre_prix"],
                    labels={
                        "mois": "Mois",
                        "prix_moyen": "Prix moyen (€ / litre)",
                        "carburant": "Carburant",
                        "nombre_prix": "Nombre de prix"
                    },
                    title="Évolution du prix moyen par carburant"
                )

                fig_evolution.update_layout(
                    template="plotly_white",
                    height=480,
                    hovermode="x unified",
                    legend_title="Carburant"
                )

                st.plotly_chart(
                    fig_evolution,
                    width="stretch"
                )

                with st.expander(
                    "Afficher les statistiques mensuelles détaillées"
                ):

                    st.dataframe(
                        df_stats_filtre,
                        width="stretch",
                        hide_index=True
                    )

            else:

                st.warning(
                    "Les statistiques mensuelles ne sont pas disponibles."
                )

            # ------------------------------------------------
            # 5. ANOMALIES PAR MOIS
            # ------------------------------------------------

            st.divider()

            st.subheader("Détection des anomalies mensuelles")

            if (
                not df_anomalies_filtre.empty
                and {
                    "mois",
                    "carburant",
                    "nombre_anomalies"
                }.issubset(df_anomalies_filtre.columns)
            ):

                fig_anomalies = px.bar(
                    df_anomalies_filtre,
                    x="mois",
                    y="nombre_anomalies",
                    color="carburant",
                    barmode="group",
                    labels={
                        "mois": "Mois",
                        "nombre_anomalies": "Nombre d'anomalies",
                        "carburant": "Carburant"
                    },
                    title="Nombre d'anomalies par mois et par carburant"
                )

                fig_anomalies.update_layout(
                    template="plotly_white",
                    height=480,
                    hovermode="x unified",
                    legend_title="Carburant"
                )

                st.plotly_chart(
                    fig_anomalies,
                    width="stretch"
                )

                # Classement des carburants
                anomalies_carburant = (
                    df_anomalies_filtre
                    .groupby("carburant")["nombre_anomalies"]
                    .sum()
                    .reset_index()
                    .sort_values(
                        "nombre_anomalies",
                        ascending=False
                    )
                )

                st.markdown("#### Répartition par carburant")

                fig_repartition = px.bar(
                    anomalies_carburant,
                    x="carburant",
                    y="nombre_anomalies",
                    color="carburant",
                    text="nombre_anomalies",
                    labels={
                        "carburant": "Carburant",
                        "nombre_anomalies": "Nombre d'anomalies"
                    }
                )

                fig_repartition.update_layout(
                    template="plotly_white",
                    showlegend=False,
                    height=350
                )

                st.plotly_chart(
                    fig_repartition,
                    width="stretch"
                )

                st.markdown("#### Détail des anomalies")

                colonnes_anomalies = [
                    colonne
                    for colonne in [
                        "mois",
                        "carburant",
                        "nombre_anomalies",
                        "q1",
                        "q3",
                        "borne_inferieure",
                        "borne_superieure",
                        "lower_bound",
                        "upper_bound"
                    ]
                    if colonne in df_anomalies_filtre.columns
                ]

                st.dataframe(
                    df_anomalies_filtre[colonnes_anomalies],
                    width="stretch",
                    hide_index=True
                )

            else:

                st.info(
                    "Aucune anomalie mensuelle disponible."
                )

            # ------------------------------------------------
            # 6. RUPTURES INCOHERENTES
            # ------------------------------------------------

            st.divider()

            st.subheader("Ruptures avec dates incohérentes")

            if not df_ruptures.empty:

                st.warning(
                    f"{format_number(len(df_ruptures))} rupture(s) "
                    "présentent une date de fin antérieure à la date "
                    "de début."
                )

                st.dataframe(
                    df_ruptures,
                    width="stretch",
                    hide_index=True
                )

            else:

                st.success(
                    "Aucune rupture avec des dates incohérentes détectée."
                )

        # ------------------------------------------------
        # 7. SYNTHESE
        # ------------------------------------------------

        st.divider()

        st.subheader("Synthèse de l'analyse")

        st.markdown(
            orchestrator.generate_advanced_interpretation(
                resultats
            )
        )

        st.caption(
            "Les observations atypiques détectées par la méthode IQR "
            "doivent être examinées avant toute décision de correction."
        )

    else:

        st.info(
            "Cliquez sur « Lancer l'analyse statistique » "
            "pour commencer."
        )



elif page == "Rapports":

    st.title("Rapports")
    st.caption(
        "Consultez, visualisez et téléchargez les rapports générés par DataPilot AI."
    )

    # ------------------------------------------------
    # 1. RECUPERATION DES RAPPORTS
    # ------------------------------------------------

    reports_dir = (
        Path(__file__).resolve().parents[1]
        / "data"
        / "processed"
        / "reports"
    )

    reports_dir.mkdir(parents=True, exist_ok=True)

    col1, col2 = st.columns([3, 1])

    with col1:
        st.subheader("Historique des rapports")

    with col2:
        if st.button("Actualiser", width="stretch"):
            st.rerun()

    reports = sorted(
        reports_dir.glob("rapport_datapilot_*.md"),
        key=lambda file: file.stat().st_mtime,
        reverse=True
    )

    # ------------------------------------------------
    # 2. STATISTIQUES
    # ------------------------------------------------

    total_reports = len(reports)

    total_size = sum(
        file.stat().st_size for file in reports
    )

    col1, col2 = st.columns(2)

    with col1:
        st.metric(
            "Nombre de rapports",
            total_reports
        )

    with col2:
        st.metric(
            "Espace utilisé",
            f"{total_size / 1024:.2f} Ko"
        )

    st.divider()

    # ------------------------------------------------
    # 3. AFFICHAGE DE L'HISTORIQUE
    # ------------------------------------------------

    if reports:

        st.markdown("### Sélectionner un rapport")

        report_options = {
            file.name: file for file in reports
        }

        selected_report = st.selectbox(
            "Rapports disponibles",
            options=list(report_options.keys()),
            format_func=lambda name: name.replace(
                "rapport_datapilot_", ""
            ).replace(".md", "").replace("_", " à ")
        )

        report_path = report_options[selected_report]

        try:

            report_content = report_path.read_text(
                encoding="utf-8"
            )

            report_date = datetime.fromtimestamp(
                report_path.stat().st_mtime
            )

            # ----------------------------------------
            # 4. INFORMATIONS DU RAPPORT
            # ----------------------------------------

            st.markdown("### Informations du rapport")

            col1, col2 = st.columns(2)

            with col1:
                st.write("**Nom du fichier**")
                st.code(report_path.name)

            with col2:
                st.write("**Date de génération**")
                st.write(
                    report_date.strftime("%d/%m/%Y à %H:%M:%S")
                )

            st.divider()

            # ----------------------------------------
            # 5. TELECHARGEMENT
            # ----------------------------------------

            st.markdown("### Télécharger le rapport")

            st.download_button(
                label="Télécharger le rapport Markdown",
                data=report_content,
                file_name=report_path.name,
                mime="text/markdown",
                width="stretch"
            )

            st.divider()

            # ----------------------------------------
            # 6. APERCU DU RAPPORT
            # ----------------------------------------

            st.markdown("### Aperçu du rapport")

            with st.container(border=True):

                st.markdown(report_content)

        except Exception as e:

            st.error(
                f"Impossible de lire le rapport : {e}"
            )

    else:

        st.info(
            "Aucun rapport disponible. "
            "Utilisez l'Assistant IA pour effectuer une analyse "
            "et générer votre premier rapport."
        )


else:

    st.title(page)

    st.info(
        "Cette section sera développée dans les prochaines étapes."
    )



