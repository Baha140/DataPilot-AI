
import pandas as pd
from pathlib import Path
import duckdb

from datapilot.agent.sql_agent import analyze_sql_results



def test_monthly_analysis():

    data = pd.DataFrame({
        "mois": [
            "2025-01-01",
            "2025-02-01",
            "2025-03-01",
            "2025-04-01",
            "2025-05-01"
        ],
        "prix_moyen": [1.70, 1.65, 1.72, 1.62, 1.68]
    })

    result = analyze_sql_results(data)

    assert result["status"] == "success"

    # Vérification des statistiques générales
    assert result["trend"]["maximum_date"] == "2025-03-01 00:00:00"
    assert result["trend"]["minimum_date"] == "2025-04-01 00:00:00"
    assert result["trend"]["direction"] == "baisse"

    # Vérification des variations entre les mois
    assert result["trend"]["nombre_hausses"] == 2
    assert result["trend"]["nombre_baisses"] == 2
    assert result["trend"]["nombre_stabilites"] == 0

    # Vérification de la plus forte hausse
    assert result["trend"]["plus_forte_hausse"]["date"] == "2025-03-01 00:00:00"
    assert abs(
        result["trend"]["plus_forte_hausse"]["variation"] - 0.07
    ) < 0.000001

    # Vérification de la plus forte baisse
    assert result["trend"]["plus_forte_baisse"]["date"] == "2025-04-01 00:00:00"
    assert abs(
        result["trend"]["plus_forte_baisse"]["variation"] - (-0.10)
    ) < 0.000001

    print("TEST 1 : Evolution mensuelle et variations reussies")



def test_missing_values():

    data = pd.DataFrame({
        "carburant": ["E10", "Gazole", "SP98"],
        "prix_moyen": [1.70, None, 1.90]
    })

    result = analyze_sql_results(data)

    assert result["statistics"]["prix_moyen"]["count"] == 2
    assert result["statistics"]["prix_moyen"]["missing"] == 1
    assert result["ranking"]["minimum"][0]["carburant"] == "E10"

    print("TEST 2 : Valeurs manquantes gerees")


def test_multiple_numeric_columns():

    data = pd.DataFrame({
        "mois": ["2025-01-01", "2025-02-01"],
        "prix_moyen": [1.70, 1.65],
        "nombre_prix": [100, 120]
    })

    result = analyze_sql_results(data)

    assert result["trend"] is None
    assert any(
        "Plusieurs colonnes numériques" in warning
        for warning in result["warnings"]
    )

    print("TEST 3 : Colonnes numeriques multiples gerees")


def test_empty_result():

    data = pd.DataFrame(columns=["carburant", "prix_moyen"])

    result = analyze_sql_results(data)

    assert result["status"] == "empty"
    assert result["total_rows"] == 0

    print("TEST 4 : Resultat vide gere")


def test_real_gazole_data():

    print("\n--- TEST SUR LES DONNEES REELLES DU GAZOLE ---")

    base_dir = Path(__file__).resolve().parents[1]
    db_path = base_dir / "data" / "processed" / "datapilot.duckdb"

    con = duckdb.connect(str(db_path), read_only=True)

    try:
        data = con.execute("""
            SELECT
                DATE_TRUNC('month', CAST(date_maj AS TIMESTAMP)) AS mois,
                AVG(prix) AS prix_moyen
            FROM prix_clean
            WHERE carburant = 'Gazole'
              AND date_maj IS NOT NULL
              AND prix IS NOT NULL
              AND prix > 0
            GROUP BY 1
            ORDER BY 1
        """).fetchdf()

    finally:
        con.close()

    result = analyze_sql_results(data)

    assert result["status"] == "success"
    assert result["total_rows"] == 12

    trend = result["trend"]

    assert trend["nombre_hausses"] == 4
    assert trend["nombre_baisses"] == 7
    assert trend["nombre_stabilites"] == 0

    print("Nombre de mois :", result["total_rows"])
    print("Nombre de hausses :", trend["nombre_hausses"])
    print("Nombre de baisses :", trend["nombre_baisses"])
    print("Nombre de stabilites :", trend["nombre_stabilites"])

    print("Plus forte hausse :", trend["plus_forte_hausse"])
    print("Plus forte baisse :", trend["plus_forte_baisse"])

    print("TEST 5 : Analyse des donnees reelles reussie")


def main():

    print("\n" + "=" * 60)
    print(" TESTS AVANCES - ANALYSE DETERMINISTE")
    print("=" * 60)

    test_monthly_analysis()
    test_missing_values()
    test_multiple_numeric_columns()
    test_empty_result()
    test_real_gazole_data()
     
    print("\nTous les tests sont reussis !")


if __name__ == "__main__":
    main()
