
import csv
from pathlib import Path
from lxml import etree


BASE_DIR = Path(__file__).resolve().parents[3]

XML_PATH = BASE_DIR / "data" / "raw" / "PrixCarburants_annuel_2025.xml"
OUTPUT_DIR = BASE_DIR / "data" / "processed"


def get_text(element, tag):
    """Récupère le texte d'une balise enfant."""
    for child in element:
        if etree.QName(child).localname == tag:
            return (child.text or "").strip()

    return ""


def load_xml_to_csv(xml_path=XML_PATH, output_dir=OUTPUT_DIR):

    xml_path = Path(xml_path)
    output_dir = Path(output_dir)

    if not xml_path.exists():
        raise FileNotFoundError(f"Fichier XML introuvable : {xml_path}")

    output_dir.mkdir(parents=True, exist_ok=True)

    stations_file = output_dir / "stations.csv"
    prices_file = output_dir / "prix.csv"
    ruptures_file = output_dir / "ruptures.csv"

    station_fields = [
        "station_id",
        "latitude",
        "longitude",
        "code_postal",
        "population_type",
        "adresse",
        "ville",
        "fermee"
    ]

    price_fields = [
        "station_id",
        "carburant",
        "carburant_id",
        "date_maj",
        "prix"
    ]

    rupture_fields = [
        "station_id",
        "carburant",
        "carburant_id",
        "date_debut",
        "date_fin",
        "type"
    ]

    station_count = 0
    price_count = 0
    rupture_count = 0

    with (
        open(stations_file, "w", newline="", encoding="utf-8") as sf,
        open(prices_file, "w", newline="", encoding="utf-8") as pf,
        open(ruptures_file, "w", newline="", encoding="utf-8") as rf
    ):

        stations_writer = csv.DictWriter(
            sf, fieldnames=station_fields
        )
        prices_writer = csv.DictWriter(
            pf, fieldnames=price_fields
        )
        ruptures_writer = csv.DictWriter(
            rf, fieldnames=rupture_fields
        )

        stations_writer.writeheader()
        prices_writer.writeheader()
        ruptures_writer.writeheader()

        print("Début de l'importation XML...")

        for event, element in etree.iterparse(
            str(xml_path),
            events=("end",),
            tag="pdv",
            recover=True,
            huge_tree=True
        ):

            station_id = element.get("id", "")

            # Informations générales de la station
            station = {
                "station_id": station_id,
                "latitude": element.get("latitude", ""),
                "longitude": element.get("longitude", ""),
                "code_postal": element.get("cp", ""),
                "population_type": element.get("pop", ""),
                "adresse": get_text(element, "adresse"),
                "ville": get_text(element, "ville"),
                "fermee": any(
                    etree.QName(child).localname == "fermeture"
                    for child in element
                )
            }

            stations_writer.writerow(station)
            station_count += 1

            # Historique des prix
            for child in element:

                tag = etree.QName(child).localname

                if tag == "prix":

                    prices_writer.writerow({
                        "station_id": station_id,
                        "carburant": child.get("nom", ""),
                        "carburant_id": child.get("id", ""),
                        "date_maj": child.get("maj", ""),
                        "prix": child.get("valeur", "")
                    })

                    price_count += 1

                # Historique des ruptures
                elif tag == "rupture":

                    ruptures_writer.writerow({
                        "station_id": station_id,
                        "carburant": child.get("nom", ""),
                        "carburant_id": child.get("id", ""),
                        "date_debut": child.get("debut", ""),
                        "date_fin": child.get("fin", ""),
                        "type": child.get("type", "")
                    })

                    rupture_count += 1

            # Libérer la mémoire progressivement
            element.clear()

            while element.getprevious() is not None:
                del element.getparent()[0]

            if station_count % 1000 == 0:
                print(f"{station_count} stations traitées...")

    print("\nImportation terminée !")
    print(f"Stations : {station_count}")
    print(f"Prix : {price_count}")
    print(f"Ruptures : {rupture_count}")

    print("\nFichiers créés :")
    print(stations_file)
    print(prices_file)
    print(ruptures_file)


if __name__ == "__main__":
    load_xml_to_csv()
