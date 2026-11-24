
from pathlib import Path

import plotly.express as px

from datapilot.analysis.query_engine import QueryEngine


BASE_DIR = Path(__file__).resolve().parents[3]

OUTPUT_DIR = BASE_DIR / "data" / "processed" / "visualizations"


def create_visualizations():

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    engine = QueryEngine()

    print("\n" + "=" * 60)
    print("       DATAPILOT AI - GENERATION DES GRAPHIQUES")
    print("=" * 60)

    try:

        # 1. Prix moyen par carburant
        print("\n1. Generation du graphique des prix moyens...")

        query = """
            SELECT
                carburant,
                ROUND(AVG(prix), 3) AS prix_moyen
            FROM prix_clean
            WHERE prix IS NOT NULL
              AND carburant IS NOT NULL
            GROUP BY carburant
            ORDER BY prix_moyen DESC
        """

        df_prix = engine.execute_query(query)

        fig_prix = px.bar(
            df_prix,
            x="carburant",
            y="prix_moyen",
            title="Prix moyen par carburant - 2025",
            labels={
                "carburant": "Type de carburant",
                "prix_moyen": "Prix moyen (€)"
            },
            text_auto=".3f",
            template="plotly_white"
        )

        fig_prix.update_layout(
            xaxis_title="Carburant",
            yaxis_title="Prix moyen (€)"
        )

        fig_prix.write_html(
            str(OUTPUT_DIR / "prix_moyens.html")
        )

        print("Graphique 1 enregistre.")

        # 2. Evolution mensuelle du Gazole
        print("\n2. Generation du graphique d'evolution...")

        query = """
            SELECT
                STRFTIME(date_maj, '%Y-%m') AS mois,
                ROUND(AVG(prix), 3) AS prix_moyen
            FROM prix_clean
            WHERE carburant = 'Gazole'
              AND date_maj IS NOT NULL
              AND prix IS NOT NULL
            GROUP BY STRFTIME(date_maj, '%Y-%m')
            ORDER BY mois
        """

        df_evolution = engine.execute_query(query)

        fig_evolution = px.line(
            df_evolution,
            x="mois",
            y="prix_moyen",
            markers=True,
            title="Evolution mensuelle du prix du Gazole - 2025",
            labels={
                "mois": "Mois",
                "prix_moyen": "Prix moyen (€)"
            },
            template="plotly_white"
        )

        fig_evolution.update_layout(
            xaxis_title="Mois",
            yaxis_title="Prix moyen (€)"
        )

        fig_evolution.write_html(
            str(OUTPUT_DIR / "evolution_gazole.html")
        )

        print("Graphique 2 enregistre.")

        # 3. Repartition des ruptures par carburant
        print("\n3. Generation du graphique des ruptures...")

        query = """
            SELECT
                carburant,
                COUNT(*) AS nombre_ruptures
            FROM ruptures_clean
            WHERE carburant IS NOT NULL
            GROUP BY carburant
            ORDER BY nombre_ruptures DESC
        """

        df_ruptures = engine.execute_query(query)

        fig_ruptures = px.pie(
            df_ruptures,
            names="carburant",
            values="nombre_ruptures",
            title="Repartition des ruptures par carburant - 2025",
            template="plotly_white",
            hole=0.35
        )

        fig_ruptures.write_html(
            str(OUTPUT_DIR / "repartition_ruptures.html")
        )

        print("Graphique 3 enregistre.")

    finally:
        engine.close()

    print("\n" + "=" * 60)
    print("Generation terminee avec succes !")
    print(f"Dossier : {OUTPUT_DIR}")
    print("=" * 60)


if __name__ == "__main__":
    create_visualizations()
