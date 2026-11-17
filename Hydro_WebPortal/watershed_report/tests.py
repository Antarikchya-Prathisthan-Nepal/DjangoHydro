import unittest
from unittest.mock import patch

import geopandas as gpd
import shapely
from shapely.geometry import MultiPolygon, Polygon, box, mapping

from . import analysis


class PreparedWatershedAnalysisTests(unittest.TestCase):
    def setUp(self):
        self.geom = MultiPolygon([
            Polygon(
                [(0, 0), (4, 0), (4, 4), (0, 4), (0, 0)],
                holes=[[(1, 1), (2, 1), (2, 2), (1, 2), (1, 1)]],
            ),
            box(6, 0, 7, 1),
        ])
        self.features = [box(0.1, 0.1, 0.5, 0.5), box(1.2, 1.2, 1.8, 1.8),
                         box(4, 2, 5, 3), box(6.1, 0.1, 6.5, 0.5),
                         box(8, 8, 9, 9)]
        shapely.prepare(self.geom)

    def test_population_and_buildings_keep_intersection_semantics(self):
        population = gpd.GeoDataFrame(
            {'VALUE': [10, 20, 30, 40, 50]}, geometry=self.features, crs='EPSG:4326'
        )
        buildings = gpd.GeoDataFrame(
            {'type': ['house', 'hole', None, 'house', 'outside']},
            geometry=self.features, crs='EPSG:4326',
        )
        with patch.object(analysis.gpd, 'read_file', side_effect=[population, buildings]):
            self.assertEqual(analysis._analyze_population(self.geom),
                             {'total': 80, 'cell_count': 3})
            self.assertEqual(analysis._analyze_buildings(self.geom), {
                'total': 3,
                'by_type': [{'type': 'house', 'count': 2},
                            {'type': 'unclassified', 'count': 1}],
            })

    def test_wards_keep_intersection_semantics(self):
        wards = gpd.GeoDataFrame({
            'DISTRICT': ['A', 'Hole', 'B', 'C', 'Outside'],
            'GaPa_NaPa': ['M', 'Hole', 'N', 'O', 'Outside'],
            'NEW_WARD_N': [1, 2, 3, 4, 5],
        }, geometry=self.features, crs='EPSG:4326')
        with patch.object(analysis, '_load_wards', return_value=wards):
            result = analysis._analyze_wards(self.geom)
        self.assertEqual(result['ward_count'], 3)
        self.assertEqual(result['districts'], ['A', 'B', 'C'])
        self.assertEqual([ward['ward_number'] for ward in result['wards']], [1, 3, 4])

    def test_analysis_prepares_geometry_before_workers(self):
        def check_prepared(geom):
            self.assertTrue(shapely.is_prepared(geom))
            return {}

        with patch.object(analysis, '_area_km2', return_value=1), \
             patch.object(analysis, '_analyze_population', side_effect=check_prepared), \
             patch.object(analysis, '_analyze_lulc', side_effect=check_prepared), \
             patch.object(analysis, '_analyze_buildings', side_effect=check_prepared), \
             patch.object(analysis, '_analyze_wards', side_effect=check_prepared), \
             patch.object(analysis, '_generate_visuals', return_value=(None, None)):
            result = analysis.analyze_area(mapping(self.geom))
        self.assertEqual(result['population'], {})
        self.assertEqual(result['buildings'], {})
        self.assertEqual(result['wards'], {})
        self.assertEqual(result['lulc'], {})


if __name__ == '__main__':
    unittest.main()
