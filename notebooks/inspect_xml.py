
from lxml import etree

xml_path = "data/raw/PrixCarburants_annuel_2025.xml"

print("Inspection du fichier XML...")

count = 0

for event, element in etree.iterparse(
    xml_path,
    events=("end",),
    recover=True,
    huge_tree=True
):
    # Identifier les éléments représentant les stations
    if etree.QName(element).localname == "pdv":
        count += 1

        print(f"\n========== STATION {count} ==========")

        # Afficher les attributs de la station
        print("Attributs :", element.attrib)

        # Afficher les premiers éléments enfants
        for child in element:
            print(
                "Balise :", etree.QName(child).localname,
                "| Attributs :", child.attrib,
                "| Texte :", (child.text or "").strip()[:100]
            )

        # Afficher uniquement les deux premières stations
        element.clear()

        if count == 2:
            break

print("\nInspection terminée.")
