
from pathlib import Path
import duckdb


BASE_DIR = Path(__file__).resolve().parents[3]

DATA_DIR = BASE_DIR / "data" / "processed"
DB_PATH = DATA_DIR / "datapilot.duckdb"


def create_database():
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    connection = duckdb.connect(str(DB_PATH))

    files = {
        "stations": DATA_DIR / "stations.csv",
        "prix": DATA_DIR / "prix.csv",
        "ruptures": DATA_DIR / "ruptures.csv"
    }

    print("Importation des fichiers dans DuckDB...\n")

    for table_name, file_path in files.items():

        if not file_path.exists():
            raise FileNotFoundError(
                f"Fichier introuvable : {file_path}"
            )

        connection.execute(
            f"""
            CREATE OR REPLACE TABLE {table_name} AS
            SELECT *
            FROM read_csv_auto(?)
            """,
            [str(file_path)]
        )

        count = connection.execute(
            f"SELECT COUNT(*) FROM {table_name}"
        ).fetchone()[0]

        print(f"Table {table_name} : {count:,} lignes")

    print("\nBase de données créée avec succès !")
    print(f"Emplacement : {DB_PATH}")

    connection.close()


if __name__ == "__main__":
    create_database()
