import unittest
import pandas as pd
import os


class TestPipeline(unittest.TestCase):

    def setUp(self):
        self.complete_path = "data/poblacion_por_cp_completo.csv"
        self.filtered_path = "data/poblacion_por_cp_filtrado.csv"

    def test_output_files_exist(self):
        self.assertTrue(os.path.exists(self.complete_path))
        self.assertTrue(os.path.exists(self.filtered_path))

    def test_complete_has_expected_columns(self):
        df = pd.read_csv(self.complete_path)
        expected_cols = ["codigo_postal", "provincia", "municipio_nombre",
                         "poblacion_actual", "poblacion_hace_5a",
                         "crecimiento_%", "supera_20k", "crecimiento_positivo"]
        for col in expected_cols:
            self.assertIn(col, df.columns, f"Missing column: {col}")

    def test_filtered_only_has_valid_rows(self):
        df = pd.read_csv(self.filtered_path)
        self.assertTrue((df["supera_20k"] == True).all())
        self.assertTrue((df["crecimiento_positivo"] == True).all())

    def test_filtered_is_subset(self):
        complete = pd.read_csv(self.complete_path)
        filtered = pd.read_csv(self.filtered_path)
        self.assertTrue(
            set(filtered["codigo_postal"]).issubset(set(complete["codigo_postal"]))
        )

    def test_growth_calculation(self):
        df = pd.read_csv(self.complete_path)
        sample = df.dropna(subset=["poblacion_actual", "poblacion_hace_5a"]).head(50)
        for _, row in sample.iterrows():
            expected = (
                (row["poblacion_actual"] - row["poblacion_hace_5a"])
                / row["poblacion_hace_5a"]
                * 100
            )
            self.assertAlmostEqual(
                row["crecimiento_%"], round(expected, 2), places=1
            )

    def test_no_negative_population(self):
        df = pd.read_csv(self.complete_path)
        self.assertTrue((df["poblacion_actual"] >= 0).all())
        self.assertTrue((df["poblacion_hace_5a"] >= 0).all())

    def test_filtered_no_duplicates(self):
        df = pd.read_csv(self.filtered_path)
        self.assertEqual(
            len(df), df["codigo_postal"].nunique(),
            "Duplicated CPs in filtered output"
        )

    def test_provinces_present_in_complete(self):
        df = pd.read_csv(self.complete_path)
        expected_provs = ["Alicante/Alacant", "Castellón/Castelló", "Valencia/València",
                          "A Coruña", "Lugo", "Ourense", "Pontevedra",
                          "Murcia", "Tarragona"]
        for prov in expected_provs:
            self.assertIn(prov, df["provincia"].unique(),
                          f"Province missing in complete: {prov}")

    def test_complete_has_price_columns(self):
        df = pd.read_csv(self.complete_path)
        price_cols = ["precio_m2", "variacion_anual_%", "variacion_maximo_%",
                      "en_maximo_historico", "precio_anual_positivo"]
        for col in price_cols:
            self.assertIn(col, df.columns, f"Missing column: {col}")

    def test_filtered_enforces_price_filter(self):
        df = pd.read_csv(self.filtered_path)
        if len(df) > 0 and df["precio_m2"].notna().any():
            self.assertTrue((df["precio_anual_positivo"] == True).all())
            self.assertTrue((df["en_maximo_historico"] == False).all())

    def test_price_columns_have_valid_types(self):
        df = pd.read_csv(self.complete_path)
        valid = df.dropna(subset=["precio_m2"])
        if len(valid) > 0:
            self.assertTrue((valid["precio_m2"] > 0).all())
            self.assertTrue((valid["variacion_anual_%"].notna().all()))


if __name__ == "__main__":
    unittest.main()
