
from pathlib import Path
from datetime import date, datetime

import duckdb
import pandas as pd


# ============================================================
# CONFIGURATION
# ============================================================

BASE_DIR = Path(__file__).resolve().parents[3]
DB_PATH = BASE_DIR / "data" / "processed" / "datapilot.duckdb"


# ============================================================
# NORMALISATION DES RESULTATS
# ============================================================

def normalize_records(records):

    normalized = []

    for record in records:

        clean_record = {}

        for key, value in record.items():

            # Transformer les valeurs manquantes en None
            if pd.isna(value):
                value = None

            # Transformer les dates en chaînes ISO
            elif isinstance(value, (datetime, date)):
                value = value.isoformat()

            # Transformer les types NumPy en types Python
            elif hasattr(value, "item"):
                value = value.item()

                if isinstance(value, (datetime, date)):
                    value = value.isoformat()

            clean_record[key] = value

        normalized.append(clean_record)

    return normalized


# ============================================================
# ANALYSE AVANCEE DES PRIX PAR MOIS
# ============================================================

def analyze_monthly_prices():

    con = duckdb.connect(str(DB_PATH), read_only=True)

    try:

        print("\n" + "=" * 65)
        print("       ANALYSE AVANCEE DES PRIX PAR MOIS")
        print("=" * 65)

        # ----------------------------------------------------
        # 1. STATISTIQUES MENSUELLES PAR CARBURANT
        # ----------------------------------------------------

        print("\n1. CALCUL DES STATISTIQUES MENSUELLES")

        monthly_stats = con.execute("""

            SELECT
                carburant,

                DATE_TRUNC(
                    'month',
                    date_maj
                ) AS mois,

                COUNT(*) AS nombre_prix,

                ROUND(AVG(prix), 3) AS prix_moyen,

                ROUND(MIN(prix), 3) AS prix_minimum,

                ROUND(MAX(prix), 3) AS prix_maximum,

                ROUND(
                    quantile_cont(prix, 0.25),
                    3
                ) AS q1,

                ROUND(
                    quantile_cont(prix, 0.75),
                    3
                ) AS q3

            FROM prix

            WHERE prix IS NOT NULL
              AND prix > 0
              AND carburant IS NOT NULL
              AND date_maj IS NOT NULL

            GROUP BY
                carburant,
                DATE_TRUNC('month', date_maj)

            ORDER BY
                mois,
                carburant

        """).fetchdf()

        print("\n--- STATISTIQUES MENSUELLES ---")

        if monthly_stats.empty:

            print("Aucune statistique mensuelle disponible.")

        else:

            print(monthly_stats.to_string(index=False))

        # ----------------------------------------------------
        # 2. DETECTION DES ANOMALIES MENSUELLES AVEC IQR
        # ----------------------------------------------------

        print("\n2. DETECTION DES ANOMALIES MENSUELLES")

        anomalies = con.execute("""

            WITH monthly_stats AS (

                SELECT
                    carburant,

                    DATE_TRUNC(
                        'month',
                        date_maj
                    ) AS mois,

                    quantile_cont(
                        prix,
                        0.25
                    ) AS q1,

                    quantile_cont(
                        prix,
                        0.75
                    ) AS q3

                FROM prix

                WHERE prix IS NOT NULL
                  AND prix > 0
                  AND carburant IS NOT NULL
                  AND date_maj IS NOT NULL

                GROUP BY
                    carburant,
                    DATE_TRUNC('month', date_maj)
            )

            SELECT

                p.carburant,

                DATE_TRUNC(
                    'month',
                    p.date_maj
                ) AS mois,

                COUNT(*) AS nombre_anomalies,

                ROUND(s.q1, 3) AS q1,

                ROUND(s.q3, 3) AS q3,

                ROUND(
                    s.q1 - 1.5 * (s.q3 - s.q1),
                    3
                ) AS borne_inferieure,

                ROUND(
                    s.q3 + 1.5 * (s.q3 - s.q1),
                    3
                ) AS borne_superieure

            FROM prix p

            JOIN monthly_stats s

                ON p.carburant = s.carburant

               AND DATE_TRUNC(
                    'month',
                    p.date_maj
               ) = s.mois

            WHERE p.prix IS NOT NULL
              AND p.prix > 0
              AND p.carburant IS NOT NULL
              AND p.date_maj IS NOT NULL

              AND (
                    p.prix < s.q1 - 1.5 * (s.q3 - s.q1)

                    OR

                    p.prix > s.q3 + 1.5 * (s.q3 - s.q1)
              )

            GROUP BY
                p.carburant,
                DATE_TRUNC('month', p.date_maj),
                s.q1,
                s.q3

            ORDER BY
                mois,
                p.carburant

        """).fetchdf()

        print("\n--- ANOMALIES PAR MOIS ---")

        if anomalies.empty:

            print("Aucune anomalie detectee.")

        else:

            print(anomalies.to_string(index=False))

        # ----------------------------------------------------
        # 3. RUPTURES AVEC DATES INCOHERENTES
        # ----------------------------------------------------

        print("\n3. CONTROLE DES RUPTURES")

        print("\n--- RUPTURES AVEC DATES INCOHERENTES ---")

        invalid = con.execute("""

            SELECT *

            FROM ruptures

            WHERE date_debut IS NOT NULL
              AND date_fin IS NOT NULL
              AND date_fin < date_debut

            ORDER BY date_debut

        """).fetchdf()

        if invalid.empty:

            print("Aucune anomalie detectee.")

        else:

            print(invalid.to_string(index=False))

        # ----------------------------------------------------
        # 4. CONTROLE DES DONNEES EXCLUES DE L'ANALYSE
        # ----------------------------------------------------

        print("\n4. CONTROLE DES DONNEES EXCLUES")

        data_quality = con.execute("""

            SELECT

                COUNT(*) AS nombre_total_lignes,

                COUNT(*) FILTER (
                    WHERE prix IS NOT NULL
                      AND prix > 0
                      AND carburant IS NOT NULL
                      AND date_maj IS NOT NULL
                ) AS nombre_lignes_analysees,

                COUNT(*) FILTER (
                    WHERE prix IS NULL
                ) AS prix_manquants,

                COUNT(*) FILTER (
                    WHERE prix <= 0
                ) AS prix_non_positifs,

                COUNT(*) FILTER (
                    WHERE carburant IS NULL
                ) AS carburants_manquants,

                COUNT(*) FILTER (
                    WHERE date_maj IS NULL
                ) AS dates_manquantes,

                COUNT(*) FILTER (
                    WHERE prix IS NULL
                       OR prix <= 0
                       OR carburant IS NULL
                       OR date_maj IS NULL
                ) AS nombre_lignes_exclues

            FROM prix

        """).fetchone()

        quality_report = {

            "nombre_total_lignes": int(data_quality[0]),

            "nombre_lignes_analysees": int(data_quality[1]),

            "prix_manquants": int(data_quality[2]),

            "prix_non_positifs": int(data_quality[3]),

            "carburants_manquants": int(data_quality[4]),

            "dates_manquantes": int(data_quality[5]),

            "nombre_lignes_exclues": int(data_quality[6])

        }

        for key, value in quality_report.items():

            print(f"{key}: {value:,}")

        # ----------------------------------------------------
        # 5. CONVERSION DES RESULTATS EN DICTIONNAIRES
        # ----------------------------------------------------

        print("\n5. PREPARATION DES RESULTATS STRUCTURES")

        monthly_records = normalize_records(
            monthly_stats.to_dict(orient="records")
        )

        anomaly_records = normalize_records(
            anomalies.to_dict(orient="records")
        )

        invalid_records = normalize_records(
            invalid.to_dict(orient="records")
        )

        # ----------------------------------------------------
        # 6. CALCUL DU RESUME GLOBAL
        # ----------------------------------------------------

        nombre_total_anomalies = (

            int(anomalies["nombre_anomalies"].sum())

            if not anomalies.empty

            else 0
        )

        nombre_mois = (

            int(monthly_stats["mois"].nunique())

            if not monthly_stats.empty

            else 0
        )

        nombre_carburants = (

            int(monthly_stats["carburant"].nunique())

            if not monthly_stats.empty

            else 0
        )

        nombre_lignes_analysees = quality_report[
            "nombre_lignes_analysees"
        ]

        resume = {

            "nombre_groupes_mensuels": len(monthly_records),

            "nombre_mois_analyses": nombre_mois,

            "nombre_carburants_analyses": nombre_carburants,

            "nombre_lignes_analysees": nombre_lignes_analysees,

            "nombre_groupes_anomalies": len(anomaly_records),

            "nombre_total_anomalies_mensuelles": (
                nombre_total_anomalies
            ),

            "nombre_ruptures_incoherentes": len(invalid_records),

            "nombre_lignes_exclues": quality_report[
                "nombre_lignes_exclues"
            ]

        }

        # ----------------------------------------------------
        # 7. RAPPORT STRUCTURE POUR L'ORCHESTRATEUR
        # ----------------------------------------------------

        report = {

            "statistiques_mensuelles": monthly_records,

            "anomalies_mensuelles": anomaly_records,

            "ruptures_dates_incoherentes": invalid_records,

            "qualite_donnees": quality_report,

            "resume": resume

        }

        # ----------------------------------------------------
        # 8. AFFICHAGE DU BILAN
        # ----------------------------------------------------

        print("\n" + "=" * 65)
        print("       RESUME DE L'ANALYSE AVANCEE")
        print("=" * 65)

        for key, value in resume.items():

            print(f"{key}: {value:,}")

        print("\nAnalyse avancee terminee avec succes.")

        print("=" * 65)

        return report

    finally:

        con.close()


# ============================================================
# EXECUTION DIRECTE
# ============================================================

if __name__ == "__main__":

    results = analyze_monthly_prices()

    print("\n--- RESUME DES RESULTATS ---")

    print(results["resume"])
