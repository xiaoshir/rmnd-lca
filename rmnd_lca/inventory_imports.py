from . import DATA_DIR
import re
import wurst
from wurst import searching as ws
from bw2io import ExcelImporter, Migration, SimaProCSVImporter
from pathlib import Path
import csv

FILEPATH_BIOSPHERE_FLOWS = (DATA_DIR / "dict_biosphere.txt")


class BaseInventoryImport():
    """
    Base class for inventories that are to be merged with the ecoinvent database.

    :ivar db: the target database for the import (the Ecoinvent database),
              unpacked to a list of dicts
    :vartype db: list
    :ivar version: the target Ecoinvent database version
    :vartype version: str
    :ivar import_db: the database to be merged with ecoinvent
    :vartype import_db: LCIImporter
    """

    def __init__(self, database, version, path):
        """Create a :class:`BaseInventoryImport` instance.

        :param list database: the target database for the import (the Ecoinvent database),
                              unpacked to a list of dicts
        :param float version: the version of the target database
        :param path: Path to the imported inventory.
        :type path: str or Path

        """
        self.db = database
        self.version = version
        self.biosphere_dict = self.get_biosphere_code()

        path = Path(path)
        if not path.is_file():
            raise FileNotFoundError("The inventory file {} could not be found.".format(path))
        self.load_inventory(path)

    def load_inventory(self, path):
        """Load an inventory from a specified path.

        Sets the :attr:`import_db` attribute.

        :param str path: Path to the inventory file
        :returns: Nothing.

        """
        pass

    def prepare_inventory(self):
        """Prepare the inventory for the merger with Ecoinvent.

        Modifies :attr:`import_db` in-place.

        :returns: Nothing

        """
        pass

    def merge_inventory(self):
        """Prepare :attr:`import_db` and merge the inventory to the ecoinvent :attr:`db`.

        Calls :meth:`prepare_inventory`. Changes the :attr:`db` attribute.

        :returns: Nothing

        """
        self.prepare_inventory()
        self.db.extend(self.import_db)

    def search_exchanges(self, srchdict):
        """Search :attr:`import_db` by field values.

        :param dict srchdict: dict with the name of the fields and the values.
        :returns: the activities with the exchanges that match the search.
        :rtype: dict

        """
        results = []
        for act in self.import_db.data:
            for ex in act["exchanges"]:
                if len(srchdict.items() - ex.items()) == 0:
                   results.append(act)
        return results

    def search_missing_field(self, field):
        """Find exchanges and activities that do not contain a specific field
        in :attr:`imort_db`

        :param str field: label of the field to search for.
        :returns: a list of dictionaries, activities and exchanges
        :rtype: list

        """
        results = []
        for act in self.import_db.data:
            if field not in act:
                results.append(act)
            for ex in act["exchanges"]:
                if ex["type"] == "technosphere" and field not in ex:
                   results.append(ex)
        return results

    def get_biosphere_code(self):
        """
        Retrieve a dictionary with biosphere flow names and uuid codes.

        :returns: dictionary with biosphere flow names as keys and uuid code as values
        :rtype: dict
        """

        if not FILEPATH_BIOSPHERE_FLOWS.is_file():
            raise FileNotFoundError(
                "The dictionary of biosphere flows could not be found."
            )

        csv_dict = {}

        with open(FILEPATH_BIOSPHERE_FLOWS) as f:
            input_dict = csv.reader(f, delimiter=";")
            for row in input_dict:
                csv_dict[(row[0], row[1], row[2], row[3])] = row[4]

        return csv_dict

    def add_product_field_to_exchanges(self):
        """Add the `product` key to the production and
        technosphere exchanges in :attr:`import_db`.

        For production exchanges, use the value of the `reference_product` field.
        For technosphere exchanges, search the activities in :attr:`import_db` and
        use the reference product. If none is found, search the Ecoinvent :attr:`db`.
        Modifies the :attr:`import_db` attribute in place.

        :raises IndexError: if no corresponding activity (and reference product) can be found.

        """
        # Add a `product` field to the production exchange
        for x in self.import_db.data:
            for y in x["exchanges"]:
                if y["type"] == "production":
                    if "product" not in y:
                        y["product"] = x["reference product"]

                    if y["name"] != x["name"]:
                        y["name"] = x["name"]

        # Add a `product` field to technosphere exchanges
        for x in self.import_db.data:
            for y in x["exchanges"]:
                if y["type"] == "technosphere":
                    # Check if the field 'product' is present
                    if not 'product' in y:
                        y['product'] = self.correct_product_field(y)

                    # If a 'reference product' field is present, we make sure it matches with the new 'product' field
                    if 'reference product' in y:
                        try:
                            assert y['product'] == y['reference product']
                        except AssertionError:
                            y['product'] = self.correct_product_field(y)

    def correct_product_field(self, exc):
        """
        Find the correct name for the `product` filed of the exchange
        :param exc: a dataset exchange
        :return: name of the product field of the exchange
        :rtype: str
        """
        # Look first in the imported inventories
        possibles = [
            a["reference product"]
            for a in self.import_db.data
            if a["name"] == exc["name"]
            and a["location"] == exc["location"]
            and a["unit"] == exc["unit"]
        ]

        # If not, look in the ecoinvent inventories
        if len(possibles) == 0:
            possibles = [
                a["reference product"]
                for a in self.db
                if a["name"] == exc["name"]
                and a["location"] == exc["location"]
                and a["unit"] == exc["unit"]
            ]
        if len(possibles) > 0:
           return possibles[0]
        else:
            raise IndexError(
                'An inventory exchange in {} cannot be linked to the biosphere or the ecoinvent database: {}'\
                    .format(self.import_db.db_name, exc['name']))


    def add_biosphere_links(self):
        """Add links for biosphere exchanges to :attr:`import_db`

        Modifies the :attr:`import_db` attribute in place.
        """
        for x in self.import_db.data:
            for y in x["exchanges"]:
                if y["type"] == "biosphere":
                    if isinstance(y["categories"], str):
                        y["categories"] = tuple(y["categories"].split("::"))
                    if len(y["categories"]) > 1:
                        y["input"] = (
                            "biosphere3",
                            self.biosphere_dict[
                                (
                                    y["name"],
                                    y["categories"][0],
                                    y["categories"][1],
                                    y["unit"],
                                )
                            ],
                        )
                    else:
                        y["input"] = (
                            "biosphere3",
                            self.biosphere_dict[
                                (
                                    y["name"],
                                    y["categories"][0],
                                    "unspecified",
                                    y["unit"],
                                )
                            ],
                        )


    def remove_ds_and_modifiy_exchanges(self, name, ex_data):
        """
        Remove an activity dataset from :attr:`import_db` and replace the corresponding
        technosphere exchanges by what is given as second argument.

        :param str name: name of activity to be removed
        :param dict ex_data: data to replace the corresponding exchanges

        :returns: Nothing
        """

        self.import_db.data = [act for act in self.import_db.data if not act["name"] == name]

        for act in self.import_db.data:
            for ex in act["exchanges"]:
                if ex["type"] == "technosphere" and ex["name"] == name:
                    ex.update(ex_data)
                    # make sure there is no existing link
                    if "input" in ex:
                        del(ex["input"])


class CarmaCCSInventory(BaseInventoryImport):
    def load_inventory(self, path):
        self.import_db = ExcelImporter(path)

    def prepare_inventory(self):
        if(self.version == 3.6):
            # apply some updates to comply with ei 3.6
            new_technosphere_data = {
                'fields': ['name', 'reference product', 'location'],
                'data': [
                    (
                        ('market for water, decarbonised, at user', (), 'GLO'),
                        {
                            'name': ('market for water, decarbonised'),
                            'reference product': ('water, decarbonised'),
                            'location': ('DE'),
                        }
                    ),
                    (
                        ('market for water, completely softened, from decarbonised water, at user', (), 'GLO'),
                        {
                            'name': ('market for water, completely softened'),
                            'reference product': ('water, completely softened'),
                            'location': ('RER'),
                        }
                    ),
                    (
                        ('market for steam, in chemical industry', (), 'GLO'),
                        {
                            'location': ('RER'),
                            'reference product': ('steam, in chemical industry'),
                        }
                    ),
                    (
                        ('market for steam, in chemical industry', (), 'RER'),
                        {
                            'reference product': ('steam, in chemical industry'),
                        }
                    ),
                    (
                        ('zinc-lead mine operation', ('zinc concentrate',), 'GLO'),
                        {
                            'name': ('zinc mine operation'),
                            'reference product': ('bulk lead-zinc concentrate'),
                        }
                    ),
                    (
                        ('market for aluminium oxide', ('aluminium oxide',), 'GLO'),
                        {
                            'name': ('market for aluminium oxide, non-metallurgical'),
                            'reference product': ('aluminium oxide, non-metallurgical'),
                            'location': ('IAI Area, EU27 & EFTA'),
                        }
                    ),
                    (
                        ('platinum group metal mine operation, ore with high rhodium content', ('nickel, 99.5%',), 'ZA'),
                        {
                            'name': ('platinum group metal, extraction and refinery operations'),
                        }
                    )
                ]
            }

            Migration("migration_36").write(
                new_technosphere_data,
                description="Change technosphere names due to change from 3.5 to 3.6"
            )
            self.import_db.migrate("migration_36")

        self.add_biosphere_links()
        self.add_product_field_to_exchanges()

        # Add carbon storage for CCS technologies
        print("Add fossil carbon dioxide storage for CCS technologies.")
        self.add_negative_CO2_flows_for_biomass_CCS()

    def add_negative_CO2_flows_for_biomass_CCS(self):
        """
        Rescale the amount of all exchanges of carbon dioxide, non-fossil by a factor -9 (.9/-.1),
        to account for sequestered CO2.

        All CO2 capture and storage in the Carma datasets is assumed to be 90% efficient.
        Thus, we can simply find out what the new CO2 emission is and then we know how much gets stored in the ground.
        It's very important that we ONLY do this for biomass CCS plants, as only they will have negative emissions!

        Modifies in place (does not return anything).

        """
        for ds in ws.get_many(self.db, ws.contains('name', 'storage'), ws.equals('database', 'Carma CCS')):
            for exc in ws.biosphere(ds, ws.equals('name', 'Carbon dioxide, non-fossil')):
                wurst.rescale_exchange(exc, (0.9 / -0.1), remove_uncertainty=True)


class BiofuelInventory(BaseInventoryImport):
    """
    Biofuel datasets from the master thesis of Francesco Cozzolino (2018).
    """

    def load_inventory(self, path):
        self.import_db = ExcelImporter(path)

    def prepare_inventory(self):

        # Migrations for 3.6
        if self.version == 3.6:
            migrations = {
                'fields': ['name','reference product', 'location'],
                'data': [
                    (
                        ('market for transport, freight, sea, transoceanic tanker', ('transport, freight, sea, transoceanic tanker',), 'GLO' ),
                        {
                            'name': ('market for transport, freight, sea, tanker for liquid goods other than petroleum and liquefied natural gas'),
                            'reference product': ('transport, freight, sea, tanker for liquid goods other than petroleum and liquefied natural gas'),
                        }
                    ),
                    (
                        ('market for water, decarbonised, at user', ('water, decarbonised, at user',), 'GLO'),
                        {
                            'name': ('market for water, decarbonised'),
                            'reference product': ('water, decarbonised'),
                            'location': ('DE'),
                        }
                    ),
                    (
                        ('market for water, completely softened, from decarbonised water, at user', ('water, completely softened, from decarbonised water, at user',), 'GLO'),
                        {
                            'name': ('market for water, completely softened'),
                            'reference product': ('water, completely softened'),
                            'location': ('RER'),
                        }
                    ),
                    (
                        ('market for concrete block', ('concrete block',), 'GLO'),
                        {
                            'location': ('DE'),
                        }
                    )
                ]
            }

            Migration("biofuels_ecoinvent_36").write(
                migrations,
                description="Change technosphere names due to change from 3.5 to 3.6"
            )
            self.import_db.migrate("biofuels_ecoinvent_36")


        self.add_biosphere_links()
        self.add_product_field_to_exchanges()
