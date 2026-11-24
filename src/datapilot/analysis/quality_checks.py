
from pathlib import Path
import duckdb


# ============================================================
# CONFIGURATION
# ============================================================

BASE_DIR = Path(__file__).resolve().parents[3]
DB_PATH = BASE_DIR / "data" / "processed" / "datapilot.duckdb"


# ============================================================
# CONTROLES DE QUALITE
# ============================================================

def run_quality_checks():

    con = duckdb.connect(str(DB_PATH), read_only=True)

    try:

        report = {}

        print("\n" + "=" * 65)
        print("       DATAPILOT AI - CONTROLE GLOBAL DE QUALITE")
        print("=" * 65)

        # ----------------------------------------------------
        # 1. PRIX MANQUANTS, NULS OU NEGATIFS
        # ----------------------------------------------------

        print("\n1. CONTROLE DES PRIX")

        # Prix manquants
        missing_prices = con.execute("""
            SELECT COUNT(*)
            FROM prix
            WHERE prix IS NULL
        """).fetchone()[0]

        # Prix egaux a zero
        zero_prices = con.execute("""
            SELECT COUNT(*)
            FROM prix
            WHERE prix = 0
        """).fetchone()[0]

        # Prix negatifs
        negative_prices = con.execute("""
            SELECT COUNT(*)
            FROM prix
            WHERE prix < 0
        """).fetchone()[0]

        report["prix_manquants"] = missing_prices
        report["prix_nuls"] = zero_prices
        report["prix_negatifs"] = negative_prices

        print(f"Prix manquants  : {missing_prices:,}")
        print(f"Prix egaux a 0  : {zero_prices:,}")
        print(f"Prix negatifs   : {negative_prices:,}")

        # ----------------------------------------------------
        # 2. DETECTION DES VALEURS ABERRANTES PAR IQR
        # ----------------------------------------------------

        print("\n2. DETECTION DES VALEURS ABERRANTES (IQR)")

        anomalies = con.execute("""
            WITH statistiques AS (
                SELECT
                    carburant,
                    quantile_cont(prix, 0.25) AS q1,
                    quantile_cont(prix, 0.75) AS q3
                FROM prix
                WHERE prix IS NOT NULL
                  AND prix > 0
                  AND carburant IS NOT NULL
                GROUP BY carburant
            )

            SELECT
                p.carburant,
                COUNT(*) AS nombre_anomalies

            FROM prix p

            JOIN statistiques s
                ON p.carburant = s.carburant

            WHERE p.prix IS NOT NULL
              AND p.prix > 0
              AND (
                    p.prix < s.q1 - 1.5 * (s.q3 - s.q1)
                    OR
                    p.prix > s.q3 + 1.5 * (s.q3 - s.q1)
              )

            GROUP BY p.carburant

            ORDER BY nombre_anomalies DESC
        """).fetchdf()

        report["anomalies_prix"] = anomalies

        if not anomalies.empty:

            print("\nAnomalies detectees par carburant :")
            print(anomalies.to_string(index=False))

            total_anomalies = int(
                anomalies["nombre_anomalies"].sum()
            )

        else:

            total_anomalies = 0
            print("Aucune anomalie detectee.")

        report["nombre_total_anomalies"] = total_anomalies

        print(f"\nTotal des anomalies : {total_anomalies:,}")

        # ----------------------------------------------------
        # 3. CONTROLE DES DATES DES PRIX
        # ----------------------------------------------------

        print("\n3. CONTROLE DES DATES")

        dates = con.execute("""
            SELECT
                MIN(date_maj) AS date_minimum,
                MAX(date_maj) AS date_maximum,
                COUNT(*) FILTER (
                    WHERE date_maj IS NULL
                ) AS dates_manquantes
            FROM prix
        """).fetchone()

        report["date_minimum"] = dates[0]
        report["date_maximum"] = dates[1]
        report["dates_manquantes"] = dates[2]

        print(f"Date minimum    : {dates[0]}")
        print(f"Date maximum    : {dates[1]}")
        print(f"Dates manquantes: {dates[2]:,}")

        # ----------------------------------------------------
        # 4. CONTROLE DES DATES DES RUPTURES
        # ----------------------------------------------------

        print("\n4. CONTROLE DES RUPTURES")

        incoherent_ruptures = con.execute("""
            SELECT COUNT(*)
            FROM ruptures
            WHERE date_debut IS NOT NULL
              AND date_fin IS NOT NULL
              AND date_fin < date_debut
        """).fetchone()[0]

        report["ruptures_dates_incoherentes"] = (
            incoherent_ruptures
        )

        print(
            "Ruptures avec dates incoherentes : "
            f"{incoherent_ruptures:,}"
        )

        # ----------------------------------------------------
        # 5. CONTROLE DES REFERENCES AUX STATIONS
        # ----------------------------------------------------

        print("\n5. CONTROLE DES REFERENCES AUX STATIONS")

        # Références station manquantes dans les prix
        missing_price_station_ids = con.execute("""
            SELECT COUNT(*)
            FROM prix
            WHERE station_id IS NULL
        """).fetchone()[0]

        # Références station manquantes dans les ruptures
        missing_rupture_station_ids = con.execute("""
            SELECT COUNT(*)
            FROM ruptures
            WHERE station_id IS NULL
        """).fetchone()[0]

        # Références non nulles mais inexistantes dans stations
        orphan_prices = con.execute("""
            SELECT COUNT(*)
            FROM prix p
            LEFT JOIN stations s
                ON p.station_id = s.station_id
            WHERE p.station_id IS NOT NULL
              AND s.station_id IS NULL
        """).fetchone()[0]

        orphan_ruptures = con.execute("""
            SELECT COUNT(*)
            FROM ruptures r
            LEFT JOIN stations s
                ON r.station_id = s.station_id
            WHERE r.station_id IS NOT NULL
              AND s.station_id IS NULL
        """).fetchone()[0]

        report["references_prix_manquantes"] = (
            missing_price_station_ids
        )

        report["references_ruptures_manquantes"] = (
            missing_rupture_station_ids
        )

        report["prix_sans_station"] = orphan_prices
        report["ruptures_sans_station"] = orphan_ruptures

        print(
            "Identifiants station manquants dans prix : "
            f"{missing_price_station_ids:,}"
        )

        print(
            "Identifiants station manquants dans ruptures : "
            f"{missing_rupture_station_ids:,}"
        )

        print(
            "Prix references a une station inexistante : "
            f"{orphan_prices:,}"
        )

        print(
            "Ruptures references a une station inexistante : "
            f"{orphan_ruptures:,}"
        )

        # ----------------------------------------------------
        # 6. CONTROLE DES COORDONNEES GEOGRAPHIQUES
        # ----------------------------------------------------

        print("\n6. CONTROLE DES COORDONNEES")

        coordinates = con.execute("""
            SELECT
                MIN(latitude) AS latitude_minimum,
                MAX(latitude) AS latitude_maximum,
                MIN(longitude) AS longitude_minimum,
                MAX(longitude) AS longitude_maximum
            FROM stations
        """).fetchone()

        missing_coordinates = con.execute("""
            SELECT COUNT(*)
            FROM stations
            WHERE latitude IS NULL
               OR longitude IS NULL
        """).fetchone()[0]

        report["latitude_minimum"] = coordinates[0]
        report["latitude_maximum"] = coordinates[1]
        report["longitude_minimum"] = coordinates[2]
        report["longitude_maximum"] = coordinates[3]
        report["coordonnees_manquantes"] = missing_coordinates

        print(f"Latitude minimum  : {coordinates[0]}")
        print(f"Latitude maximum  : {coordinates[1]}")
        print(f"Longitude minimum : {coordinates[2]}")
        print(f"Longitude maximum : {coordinates[3]}")

        print(
            "Stations avec au moins une coordonnee manquante : "
            f"{missing_coordinates:,}"
        )

        # ----------------------------------------------------
        # 7. BILAN GLOBAL
        # ----------------------------------------------------

        print("\n" + "=" * 65)
        print("                  BILAN GLOBAL")
        print("=" * 65)

        print(f"Prix manquants                 : {missing_prices:,}")
        print(f"Prix egaux a zero              : {zero_prices:,}")
        print(f"Prix negatifs                  : {negative_prices:,}")
        print(f"Anomalies statistiques (IQR)   : {total_anomalies:,}")
        print(f"Dates de prix manquantes       : {dates[2]:,}")
        print(f"Ruptures incoherentes          : {incoherent_ruptures:,}")
        print(f"References prix manquantes     : {missing_price_station_ids:,}")
        print(f"References ruptures manquantes : {missing_rupture_station_ids:,}")
        print(f"Prix sans station              : {orphan_prices:,}")
        print(f"Ruptures sans station          : {orphan_ruptures:,}")
        print(f"Coordonnees manquantes         : {missing_coordinates:,}")

        print("\nControle de qualite termine.")
        print("=" * 65)

        return report

    finally:
        con.close()


# ============================================================
# EXECUTION DIRECTE
# ============================================================

if __name__ == "__main__":
    run_quality_checks()
