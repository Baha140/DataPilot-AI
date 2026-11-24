
from pathlib import Path
import duckdb


# ============================================================
# CONFIGURATION
# ============================================================

BASE_DIR = Path(__file__).resolve().parents[3]
DB_PATH = BASE_DIR / "data" / "processed" / "datapilot.duckdb"


# ============================================================
# NETTOYAGE INTELLIGENT
# ============================================================

def create_clean_tables():

    con = duckdb.connect(str(DB_PATH))

    try:

        print("\n" + "=" * 65)
        print("       DATAPILOT AI - NETTOYAGE INTELLIGENT")
        print("=" * 65)

        report = {}

        # ----------------------------------------------------
        # 1. NETTOYAGE DES STATIONS
        # ----------------------------------------------------

        print("\n1. Preparation de la table stations_clean...")

        con.execute("""
            CREATE OR REPLACE TABLE stations_clean AS

            WITH donnees_normalisees AS (
                SELECT
                    station_id,
                    latitude,
                    longitude,
                    NULLIF(TRIM(code_postal), '') AS code_postal,
                    NULLIF(TRIM(population_type), '') AS population_type,
                    NULLIF(TRIM(adresse), '') AS adresse,
                    NULLIF(TRIM(ville), '') AS ville,
                    fermee

                FROM stations
            )

            SELECT
                station_id,
                latitude,
                longitude,
                code_postal,
                population_type,
                adresse,
                ville,
                fermee,

                -- Indicateur de coordonnées manquantes
                (
                    latitude IS NULL
                    OR longitude IS NULL
                ) AS coordonnees_manquantes,

                -- Statut principal
                CASE
                    WHEN latitude IS NULL
                         OR longitude IS NULL
                        THEN 'COORDONNEES_MANQUANTES'

                    ELSE 'A_VERIFIER'
                END AS qualite_coordonnees

            FROM donnees_normalisees
        """)

        # ----------------------------------------------------
        # 2. NETTOYAGE DES PRIX
        # ----------------------------------------------------

        print("2. Preparation de la table prix_clean...")

        con.execute("""
            CREATE OR REPLACE TABLE prix_clean AS

            WITH donnees_normalisees AS (
                SELECT
                    station_id,
                    NULLIF(TRIM(carburant), '') AS carburant,
                    carburant_id,
                    date_maj,
                    prix

                FROM prix
            )

            SELECT
                station_id,
                carburant,
                carburant_id,
                date_maj,
                prix,

                -- Indicateurs individuels
                (station_id IS NULL)
                    AS station_id_manquant,

                (carburant IS NULL)
                    AS carburant_manquant,

                (carburant_id IS NULL)
                    AS carburant_id_manquant,

                (date_maj IS NULL)
                    AS date_manquante,

                (prix IS NULL)
                    AS prix_manquant,

                (
                    prix IS NOT NULL
                    AND prix <= 0
                ) AS prix_invalide,

                -- Statut principal
                CASE
                    WHEN station_id IS NULL
                        THEN 'STATION_ID_MANQUANT'

                    WHEN carburant IS NULL
                        THEN 'CARBURANT_MANQUANT'

                    WHEN carburant_id IS NULL
                        THEN 'IDENTIFIANT_MANQUANT'

                    WHEN date_maj IS NULL
                        THEN 'DATE_MANQUANTE'

                    WHEN prix IS NULL
                        THEN 'PRIX_MANQUANT'

                    WHEN prix <= 0
                        THEN 'PRIX_INVALIDE'

                    ELSE 'OK'
                END AS qualite_statut

            FROM donnees_normalisees
        """)

        # ----------------------------------------------------
        # 3. NETTOYAGE DES RUPTURES
        # ----------------------------------------------------

        print("3. Preparation de la table ruptures_clean...")

        con.execute("""
            CREATE OR REPLACE TABLE ruptures_clean AS

            WITH donnees_normalisees AS (
                SELECT
                    station_id,
                    NULLIF(TRIM(carburant), '') AS carburant,
                    carburant_id,
                    date_debut,
                    date_fin,
                    NULLIF(TRIM(type), '') AS type

                FROM ruptures
            )

            SELECT
                station_id,
                carburant,
                carburant_id,
                date_debut,
                date_fin,
                type,

                -- Indicateurs individuels
                (station_id IS NULL)
                    AS station_id_manquant,

                (date_debut IS NULL)
                    AS date_debut_manquante,

                (
                    date_fin IS NOT NULL
                    AND date_debut IS NOT NULL
                    AND date_fin < date_debut
                ) AS date_incoherente,

                (carburant IS NULL)
                    AS carburant_manquant,

                (carburant_id IS NULL)
                    AS carburant_id_manquant,

                (type IS NULL)
                    AS type_manquant,

                -- Information : date de fin absente
                -- Ce n'est pas automatiquement une erreur.
                (date_fin IS NULL)
                    AS date_fin_absente,

                -- Statut principal
                CASE
                    WHEN station_id IS NULL
                        THEN 'STATION_ID_MANQUANT'

                    WHEN date_debut IS NULL
                        THEN 'DATE_DEBUT_MANQUANTE'

                    WHEN date_fin IS NOT NULL
                         AND date_fin < date_debut
                        THEN 'DATE_INCOHERENTE'

                    WHEN carburant IS NULL
                        THEN 'CARBURANT_MANQUANT'

                    WHEN carburant_id IS NULL
                        THEN 'IDENTIFIANT_MANQUANT'

                    WHEN type IS NULL
                        THEN 'TYPE_MANQUANT'

                    ELSE 'OK'
                END AS qualite_statut

            FROM donnees_normalisees
        """)

        # ----------------------------------------------------
        # 4. COLLECTE DES RESULTATS
        # ----------------------------------------------------

        print("\n--- BILAN DU NETTOYAGE ---")

        tables = {
            "stations_clean": "qualite_coordonnees",
            "prix_clean": "qualite_statut",
            "ruptures_clean": "qualite_statut"
        }

        for table, column in tables.items():

            total = con.execute(
                f"SELECT COUNT(*) FROM {table}"
            ).fetchone()[0]

            results = con.execute(f"""
                SELECT
                    {column},
                    COUNT(*) AS nombre

                FROM {table}

                GROUP BY {column}

                ORDER BY nombre DESC
            """).fetchall()

            status_report = {
                status: count
                for status, count in results
            }

            report[table] = {
                "total_lignes": total,
                "statuts": status_report
            }

            print(f"\n{table} : {total:,} lignes")

            for status, count in results:
                print(f"  {status}: {count:,}")

        # ----------------------------------------------------
        # 5. BILAN DES INDICATEURS INDIVIDUELS
        # ----------------------------------------------------

        print("\n--- DETAIL DES PROBLEMES DETECTES ---")

        # Prix
        prix_flags = con.execute("""
            SELECT
                COUNT(*) FILTER (
                    WHERE station_id_manquant
                ) AS station_id_manquant,

                COUNT(*) FILTER (
                    WHERE carburant_manquant
                ) AS carburant_manquant,

                COUNT(*) FILTER (
                    WHERE carburant_id_manquant
                ) AS carburant_id_manquant,

                COUNT(*) FILTER (
                    WHERE date_manquante
                ) AS date_manquante,

                COUNT(*) FILTER (
                    WHERE prix_manquant
                ) AS prix_manquant,

                COUNT(*) FILTER (
                    WHERE prix_invalide
                ) AS prix_invalide

            FROM prix_clean
        """).fetchone()

        report["prix_clean"]["indicateurs"] = {
            "station_id_manquant": prix_flags[0],
            "carburant_manquant": prix_flags[1],
            "carburant_id_manquant": prix_flags[2],
            "date_manquante": prix_flags[3],
            "prix_manquant": prix_flags[4],
            "prix_invalide": prix_flags[5]
        }

        print("\nPrix :")

        for key, value in report["prix_clean"]["indicateurs"].items():
            print(f"  {key}: {value:,}")

        # Ruptures
        rupture_flags = con.execute("""
            SELECT
                COUNT(*) FILTER (
                    WHERE station_id_manquant
                ) AS station_id_manquant,

                COUNT(*) FILTER (
                    WHERE date_debut_manquante
                ) AS date_debut_manquante,

                COUNT(*) FILTER (
                    WHERE date_incoherente
                ) AS date_incoherente,

                COUNT(*) FILTER (
                    WHERE carburant_manquant
                ) AS carburant_manquant,

                COUNT(*) FILTER (
                    WHERE carburant_id_manquant
                ) AS carburant_id_manquant,

                COUNT(*) FILTER (
                    WHERE type_manquant
                ) AS type_manquant,

                COUNT(*) FILTER (
                    WHERE date_fin_absente
                ) AS date_fin_absente

            FROM ruptures_clean
        """).fetchone()

        report["ruptures_clean"]["indicateurs"] = {
            "station_id_manquant": rupture_flags[0],
            "date_debut_manquante": rupture_flags[1],
            "date_incoherente": rupture_flags[2],
            "carburant_manquant": rupture_flags[3],
            "carburant_id_manquant": rupture_flags[4],
            "type_manquant": rupture_flags[5],
            "date_fin_absente": rupture_flags[6]
        }

        print("\nRuptures :")

        for key, value in report["ruptures_clean"]["indicateurs"].items():
            print(f"  {key}: {value:,}")

        # Stations
        station_flags = con.execute("""
            SELECT
                COUNT(*) FILTER (
                    WHERE coordonnees_manquantes
                )
            FROM stations_clean
        """).fetchone()[0]

        report["stations_clean"]["indicateurs"] = {
            "coordonnees_manquantes": station_flags
        }

        print("\nStations :")
        print(f"  Coordonnees manquantes: {station_flags:,}")

        # ----------------------------------------------------
        # 6. VERIFICATION DE LA CONSERVATION DES DONNEES
        # ----------------------------------------------------

        print("\n--- VERIFICATION DE LA CONSERVATION ---")

        tables_originales = [
            "stations",
            "prix",
            "ruptures"
        ]

        conservation_ok = True

        for table in tables_originales:

            nombre_original = con.execute(
                f"SELECT COUNT(*) FROM {table}"
            ).fetchone()[0]

            nombre_clean = con.execute(
                f"SELECT COUNT(*) FROM {table}_clean"
            ).fetchone()[0]

            identique = nombre_original == nombre_clean

            print(
                f"{table}: original={nombre_original:,} | "
                f"clean={nombre_clean:,} | "
                f"{'OK' if identique else 'ERREUR'}"
            )

            if not identique:
                conservation_ok = False

        report["conservation_donnees"] = conservation_ok

        # ----------------------------------------------------
        # 7. BILAN FINAL
        # ----------------------------------------------------

        print("\n" + "=" * 65)
        print("                  BILAN FINAL")
        print("=" * 65)

        if conservation_ok:
            print("Toutes les lignes originales ont ete conservees.")
        else:
            print("ATTENTION : difference detectee dans le nombre de lignes.")

        print("Les tables originales n'ont pas ete modifiees.")
        print("Les trois tables nettoyees ont ete creees avec succes.")

        print("\nNettoyage termine !")
        print("=" * 65)

        return report

    finally:
        con.close()


# ============================================================
# EXECUTION DIRECTE
# ============================================================

if __name__ == "__main__":

    results = create_clean_tables()

    print("\nResultats structures disponibles :")
    print(results)
