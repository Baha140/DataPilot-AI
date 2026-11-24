from pathlib import Path
import duckdb
import pandas as pd


BASE_DIR = Path(__file__).resolve().parents[3]
DB_PATH = BASE_DIR / "data" / "processed" / "datapilot.duckdb"


def diagnose_table(table_name):
    """
    Analyse automatiquement la qualité d'une table DuckDB.
    """

    allowed_tables = ["stations", "prix", "ruptures"]

    if table_name not in allowed_tables:
        raise ValueError("Table non autorisée.")

    connection = duckdb.connect(str(DB_PATH), read_only=True)

    print("\n" + "=" * 55)
    print(f"       DIAGNOSTIC DE LA TABLE : {table_name.upper()}")
    print("=" * 55)

    # 1. Nombre de lignes
    total_rows = connection.execute(
        f"SELECT COUNT(*) FROM {table_name}"
    ).fetchone()[0]

    # 2. Informations sur les colonnes
    columns = connection.execute(
        f"DESCRIBE SELECT * FROM {table_name}"
    ).fetchdf()

    print(f"\nNombre de lignes : {total_rows:,}")
    print(f"Nombre de colonnes : {len(columns)}")

    print("\n--- TYPES DES COLONNES ---")
    print(columns[["column_name", "column_type"]].to_string(index=False))

    # 3. Valeurs manquantes
    print("\n--- VALEURS MANQUANTES ---")

    missing_query = ", ".join(
        [
            f'COUNT(*) FILTER (WHERE "{col}" IS NULL) AS "{col}"'
            for col in columns["column_name"]
        ]
    )

    missing = connection.execute(
        f"SELECT {missing_query} FROM {table_name}"
    ).fetchdf()

    for column in columns["column_name"]:
        count = int(missing.iloc[0][column])
        percentage = (count / total_rows * 100) if total_rows else 0

        print(
            f"{column}: {count:,} valeurs manquantes "
            f"({percentage:.2f} %)"
        )

    # 4. Doublons de lignes
    duplicate_count = connection.execute(
        f"""
        SELECT COUNT(*)
        FROM (
            SELECT *
            FROM {table_name}
            GROUP BY ALL
            HAVING COUNT(*) > 1
        ) AS duplicates
        """
    ).fetchone()[0]

    print(f"\nNombre de groupes de lignes dupliquées : {duplicate_count:,}")

    # 5. Statistiques descriptives
    print("\n--- APERÇU DES DONNÉES ---")

    sample = connection.execute(
        f"SELECT * FROM {table_name} LIMIT 5"
    ).fetchdf()

    print(sample.to_string(index=False))

    connection.close()

    return {
        "table": table_name,
        "total_rows": total_rows,
        "total_columns": len(columns),
        "missing_values": missing.to_dict(orient="records"),
        "duplicate_groups": duplicate_count
    }


if __name__ == "__main__":

    for table in ["stations", "prix", "ruptures"]:
        diagnose_table(table)
