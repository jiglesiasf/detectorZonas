import unittest
import pandas as pd
import os
from pathlib import Path


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
            # variacion_anual may be null for Notariado-only CPs (no MIVAU fallback)


class TestNotariadoIntegration(unittest.TestCase):

    def setUp(self):
        self.complete_path = "data/poblacion_por_cp_completo.csv"
        self.notariado_path = "data/precios_notariado.csv"

    def test_fuente_precio_column_exists(self):
        df = pd.read_csv(self.complete_path)
        self.assertIn("fuente_precio", df.columns, "Missing column: fuente_precio")

    def test_fuente_precio_has_valid_values(self):
        df = pd.read_csv(self.complete_path)
        valid = df["fuente_precio"].dropna().unique()
        for v in valid:
            self.assertIn(v, ["notariado", "mivau"],
                          f"Unexpected fuente_precio value: {v}")

    def test_notariado_is_primary_source(self):
        """When Notariado has price for a CP, fuente_precio should be notariado."""
        df = pd.read_csv(self.complete_path)
        notariado_rows = df[df["fuente_precio"] == "notariado"]
        if len(notariado_rows) > 0:
            self.assertTrue((notariado_rows["precio_m2"].notna()).all(),
                            "Notariado-sourced CPs should have precio_m2")

    def test_merge_notariado_priority(self):
        """Unit test: merge_notariado should fill prices by CP match, not municipio."""
        from pipeline import merge_notariado, load_notariado

        notariado_path = Path(self.notariado_path)
        if not notariado_path.exists():
            self.skipTest("precios_notariado.csv not available")

        notariado_df = load_notariado()
        sample_cp = notariado_df["codigo_postal"].iloc[0]
        sample_price = notariado_df["precio_m2"].iloc[0]

        cp_df = pd.DataFrame({
            "codigo_postal": [sample_cp, "99999"],
            "municipio_nombre": ["Test", "Unknown"],
        })
        result = merge_notariado(cp_df, notariado_df)
        self.assertEqual(result.loc[0, "precio_m2"], sample_price)
        self.assertTrue(pd.isna(result.loc[1, "precio_m2"]))

    def test_merge_mivau_variacion_fills_vars(self):
        """Unit test: merge_mivau_variacion fills variacion columns from MIVAU."""
        from pipeline import load_mivau, merge_mivau_variacion

        mivau_path = Path("data/precios_mivau.csv")
        if not mivau_path.exists():
            self.skipTest("precios_mivau.csv not available")

        _, mivau_mapping = load_mivau()
        cp_df = pd.DataFrame({
            "codigo_postal": ["46001"],
            "municipio_nombre": ["València"],
            "precio_m2": [2500.0],
        })
        result = merge_mivau_variacion(cp_df, mivau_mapping)
        self.assertIn("variacion_anual", result.columns)
        self.assertIn("en_maximo_historico", result.columns)

    def test_fuente_precio_mivau_fallback(self):
        """When notariado unavailable, all CPs should have fuente_precio='mivau'."""
        df = pd.read_csv(self.complete_path)
        if not os.path.exists(self.notariado_path):
            unique_sources = df["fuente_precio"].dropna().unique()
            if len(unique_sources) > 0:
                self.assertEqual(set(unique_sources), {"mivau"})

    def test_no_bc_to_existing_price_columns(self):
        """Adding fuente_precio should not break existing price columns."""
        df = pd.read_csv(self.complete_path)
        expected = ["precio_m2", "variacion_anual_%", "variacion_maximo_%",
                    "en_maximo_historico", "precio_anual_positivo", "fuente_precio"]
        for col in expected:
            self.assertIn(col, df.columns)


class TestAmenityIntegration(unittest.TestCase):

    def setUp(self):
        self.complete_path = "data/poblacion_por_cp_completo.csv"

    def test_amenity_columns_exist(self):
        df = pd.read_csv(self.complete_path)
        expected = ["tiene_supermercado", "tiene_colegio", "tiene_instituto",
                    "tiene_universidad", "tiene_centro_salud", "tiene_todos_servicios"]
        for col in expected:
            self.assertIn(col, df.columns, f"Missing column: {col}")

    def test_amenity_columns_are_boolean(self):
        df = pd.read_csv(self.complete_path)
        for col in ["tiene_supermercado", "tiene_colegio", "tiene_instituto",
                     "tiene_universidad", "tiene_centro_salud", "tiene_todos_servicios"]:
            self.assertTrue(df[col].dropna().isin([True, False]).all(),
                            f"{col} contains non-boolean values")

    def test_todos_servicios_matches_all_individual(self):
        df = pd.read_csv(self.complete_path)
        calculated = (
            df["tiene_supermercado"]
            & df["tiene_colegio"]
            & df["tiene_instituto"]
            & df["tiene_universidad"]
            & df["tiene_centro_salud"]
        )
        self.assertTrue((df["tiene_todos_servicios"] == calculated).all())

    def test_health_centers_coverage(self):
        df = pd.read_csv(self.complete_path)
        self.assertGreater(df["tiene_centro_salud"].sum(), 500,
                           "Expected 500+ CPs with health centers")

    def test_supermarkets_coverage(self):
        df = pd.read_csv(self.complete_path)
        self.assertGreater(df["tiene_supermercado"].sum(), 100,
                           "Expected 100+ CPs with supermarkets")

    def test_mercadona_column_exists(self):
        df = pd.read_csv(self.complete_path)
        self.assertIn("tiene_mercadona", df.columns,
                       "Missing column: tiene_mercadona")

    def test_mercadona_is_boolean(self):
        df = pd.read_csv(self.complete_path)
        col = df["tiene_mercadona"].dropna()
        self.assertTrue(col.isin([True, False]).all(),
                        "tiene_mercadona contains non-boolean values")


if __name__ == "__main__":
    unittest.main()
