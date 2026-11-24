
from datapilot.agent.sql_agent import (
    correct_sql,
    validate_sql
)

from datapilot.analysis.query_engine import QueryEngine


def test_sql_correction():

    question = "Quel est le prix moyen du Gazole en 2025 ?"

    incorrect_sql = """
    SELECT AVG(prix_inexistant) AS prix_moyen
    FROM prix_clean
    WHERE carburant = 'Gazole'
    """

    error = """
    Binder Error: Referenced column "prix_inexistant" not found.
    Candidate bindings: "prix"
    """

    print("\n========================================")
    print(" TEST DE CORRECTION AUTOMATIQUE")
    print("========================================")

    print("\n1. Requête incorrecte :")
    print(incorrect_sql)

    print("\n2. Envoi de l'erreur à Qwen...")

    corrected_sql, explanation = correct_sql(
        question,
        incorrect_sql,
        error
    )

    print("\n3. Requête corrigée :")
    print(corrected_sql)

    print("\n4. Explication de Qwen :")
    print(explanation)

    engine = QueryEngine()

    try:

        print("\n5. Validation et exécution...")

        validated_sql = validate_sql(corrected_sql)

        result = engine.execute_query(validated_sql)

        print("\nRésultat :")
        print(result.to_string(index=False))

        print("\nTEST DE CORRECTION REUSSI !")

    finally:
        engine.close()


def test_sql_security():

    print("\n========================================")
    print(" TEST DE SECURITE SQL")
    print("========================================")

    allowed_queries = [
        "SELECT AVG(prix) FROM prix_clean",
        "SELECT COUNT(*) FROM stations_clean;",
        "SELECT * FROM prix_clean WHERE carburant = 'DELETE'"
    ]

    forbidden_queries = [
        "DELETE FROM prix_clean",
        "DROP TABLE prix_clean",
        "SELECT * FROM users",
        "SELECT * FROM prix_clean, stations",
        "SELECT * FROM prix_clean JOIN users ON prix_clean.station_id = users.id",
        "SELECT * FROM (SELECT * FROM prix_clean) AS t",
        "WITH temp AS (SELECT * FROM prix_clean) SELECT * FROM temp",
        "SELECT * FROM read_csv_auto('data.csv')",
        "SELECT * FROM prix_clean; SELECT * FROM stations_clean"
    ]

    print("\n1. Vérification des requêtes autorisées...")

    for sql in allowed_queries:

        try:
            validate_sql(sql)
            print("[OK] Requête autorisée")

        except ValueError as error:
            raise AssertionError(
                f"Une requête valide a été refusée : {sql}\n{error}"
            )

    print("\n2. Vérification des requêtes interdites...")

    for sql in forbidden_queries:

        try:
            validate_sql(sql)

            raise AssertionError(
                f"Une requête interdite a été acceptée : {sql}"
            )

        except ValueError:
            print("[OK] Requête interdite bloquée")

    print("\nTESTS DE SECURITE REUSSIS !")


if __name__ == "__main__":

    test_sql_correction()

    test_sql_security()

    print("\n========================================")
    print(" TOUS LES TESTS SONT TERMINES")
    print("========================================")
