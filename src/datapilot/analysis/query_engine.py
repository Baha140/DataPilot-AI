
import re
from pathlib import Path

import duckdb


# ============================================================
# CONFIGURATION
# ============================================================

BASE_DIR = Path(__file__).resolve().parents[3]

DB_PATH = BASE_DIR / "data" / "processed" / "datapilot.duckdb"

ALLOWED_TABLES = {
    "stations_clean",
    "prix_clean",
    "ruptures_clean"
}


# ============================================================
# MOTEUR DE REQUETES SQL
# ============================================================

class QueryEngine:

    def __init__(self):

        if not DB_PATH.exists():
            raise FileNotFoundError(
                f"Base de donnees introuvable : {DB_PATH}"
            )

        self.connection = duckdb.connect(
            database=str(DB_PATH),
            read_only=True,
            config={
                "enable_external_access": "false"
            }
        )

        self.closed = False

    # --------------------------------------------------------
    # VERIFICATION DES INSTRUCTIONS SQL
    # --------------------------------------------------------

    @staticmethod
    def _remove_leading_comments(sql):

        """
        Supprime les commentaires situes au debut de la requete.
        """

        pattern = r"^(?:\s|--[^\n]*\n|/\*.*?\*/)*"

        return re.sub(
            pattern,
            "",
            sql,
            flags=re.DOTALL
        )

    @staticmethod
    def _has_multiple_statements(sql):

        """
        Detecte les points-virgules situes hors des chaines
        de caracteres et des commentaires SQL.
        """

        in_single_quote = False
        in_double_quote = False
        in_line_comment = False
        in_block_comment = False

        i = 0

        while i < len(sql):

            char = sql[i]
            next_char = sql[i + 1] if i + 1 < len(sql) else ""

            if in_line_comment:
                if char == "\n":
                    in_line_comment = False

            elif in_block_comment:
                if char == "*" and next_char == "/":
                    in_block_comment = False
                    i += 1

            elif in_single_quote:
                if char == "'" and next_char == "'":
                    i += 1
                elif char == "'":
                    in_single_quote = False

            elif in_double_quote:
                if char == '"' and next_char == '"':
                    i += 1
                elif char == '"':
                    in_double_quote = False

            else:

                if char == "-" and next_char == "-":
                    in_line_comment = True
                    i += 1

                elif char == "/" and next_char == "*":
                    in_block_comment = True
                    i += 1

                elif char == "'":
                    in_single_quote = True

                elif char == '"':
                    in_double_quote = True

                elif char == ";":
                    # Un point-virgule final est autorise.
                    remaining = sql[i + 1:].strip()

                    if remaining:
                        return True

            i += 1

        return False

    def _validate_sql(self, sql):

        """
        Valide une requete SQL avant son execution.
        """

        if not isinstance(sql, str):
            raise TypeError(
                "La requete SQL doit etre une chaine de caracteres."
            )

        sql = sql.strip()

        if not sql:
            raise ValueError(
                "La requete SQL est vide."
            )

        # Retirer les commentaires initiaux.
        cleaned_sql = self._remove_leading_comments(sql).strip()

        if not cleaned_sql:
            raise ValueError(
                "La requete SQL ne contient aucune instruction."
            )

        # Autoriser uniquement SELECT et WITH.
        first_word = re.match(
            r"([A-Za-z]+)",
            cleaned_sql
        )

        if not first_word:
            raise ValueError(
                "Impossible de determiner le type de requete SQL."
            )

        command = first_word.group(1).upper()

        if command not in {"SELECT", "WITH"}:
            raise ValueError(
                "Seules les requetes SELECT et WITH sont autorisees."
            )

        # Refuser plusieurs instructions.
        if self._has_multiple_statements(sql):
            raise ValueError(
                "Une seule requete SQL est autorisee."
            )

        # Retirer le point-virgule final.
        sql = sql.rstrip()

        if sql.endswith(";"):
            sql = sql[:-1].rstrip()

        return sql

    # --------------------------------------------------------
    # EXECUTION SQL
    # --------------------------------------------------------

    def execute_query(self, sql):

        """
        Execute une requete SQL en lecture seule.

        Retourne les resultats sous forme de DataFrame.
        """

        if self.closed:
            raise RuntimeError(
                "La connexion DuckDB est deja fermee."
            )

        sql = self._validate_sql(sql)

        try:

            result = self.connection.execute(sql)

            return result.fetchdf()

        except Exception as error:

            raise RuntimeError(
                f"Erreur lors de l'execution SQL : {error}"
            ) from error

    # --------------------------------------------------------
    # INFORMATIONS SUR LES TABLES
    # --------------------------------------------------------

    def get_table_info(self, table_name):

        """
        Retourne la structure d'une table autorisee.
        """

        if self.closed:
            raise RuntimeError(
                "La connexion DuckDB est deja fermee."
            )

        if not isinstance(table_name, str):
            raise TypeError(
                "Le nom de la table doit etre une chaine."
            )

        table_name = table_name.strip()

        if table_name not in ALLOWED_TABLES:
            raise ValueError(
                f"Table non autorisee : {table_name}"
            )

        try:

            return self.connection.execute(
                f"DESCRIBE {table_name}"
            ).fetchdf()

        except Exception as error:

            raise RuntimeError(
                f"Impossible de consulter la table {table_name} : {error}"
            ) from error

    # --------------------------------------------------------
    # FERMETURE DE LA CONNEXION
    # --------------------------------------------------------

    def close(self):

        if not self.closed:

            self.connection.close()
            self.closed = True

    # --------------------------------------------------------
    # CONTEXT MANAGER
    # --------------------------------------------------------

    def __enter__(self):

        return self

    def __exit__(self, exc_type, exc_value, traceback):

        self.close()


# ============================================================
# TEST DU MOTEUR SQL
# ============================================================

def test_query_engine():

    print("\n" + "=" * 60)
    print("       DATAPILOT AI - MOTEUR DE REQUETES SQL")
    print("=" * 60)

    with QueryEngine() as engine:

        # ----------------------------------------------------
        # TEST 1 : PRIX MOYEN PAR CARBURANT
        # ----------------------------------------------------

        print("\n1. PRIX MOYEN PAR CARBURANT")

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

        result = engine.execute_query(query)

        print(result.to_string(index=False))

        # ----------------------------------------------------
        # TEST 2 : EVOLUTION MENSUELLE DU GAZOLE
        # ----------------------------------------------------

        print("\n2. EVOLUTION MENSUELLE DU GAZOLE")

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

        result = engine.execute_query(query)

        print(result.to_string(index=False))

        # ----------------------------------------------------
        # TEST 3 : NOMBRE DE RUPTURES PAR CARBURANT
        # ----------------------------------------------------

        print("\n3. RUPTURES PAR CARBURANT")

        query = """
            SELECT
                carburant,
                COUNT(*) AS nombre_ruptures
            FROM ruptures_clean
            GROUP BY carburant
            ORDER BY nombre_ruptures DESC
        """

        result = engine.execute_query(query)

        print(result.to_string(index=False))

        # ----------------------------------------------------
        # TEST 4 : STRUCTURE DE LA TABLE STATIONS
        # ----------------------------------------------------

        print("\n4. STRUCTURE DE LA TABLE STATIONS")

        result = engine.get_table_info("stations_clean")

        print(result.to_string(index=False))

        # ----------------------------------------------------
        # TEST 5 : VERIFICATION DE SECURITE
        # ----------------------------------------------------

        print("\n5. TESTS DE SECURITE SQL")

        malicious_queries = [
            "DELETE FROM prix_clean",
            "DROP TABLE prix_clean",
            "SELECT * FROM prix_clean; DROP TABLE stations_clean",
            "COPY prix_clean TO 'test.csv'",
        ]

        for query in malicious_queries:

            try:

                engine.execute_query(query)

                print(f"ECHEC : requete acceptee : {query}")

            except (ValueError, RuntimeError):

                print("BLOQUE : requete non autorisee.")

    print("\nConnexion DuckDB fermee.")
    print("Tests du moteur SQL termines.")


if __name__ == "__main__":

    test_query_engine()
