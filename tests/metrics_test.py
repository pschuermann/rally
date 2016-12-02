import datetime
import unittest.mock as mock
from unittest import TestCase

from esrally import config, metrics, track


class MockClientFactory:
    def __init__(self, config):
        self._es = mock.create_autospec(metrics.EsClient)

    def create(self):
        return self._es


class DummyIndexTemplateProvider:
    def __init__(self, config):
        pass

    def template(self):
        return "test-template"


class StaticClock:
    NOW = 1453362707

    @staticmethod
    def now():
        return StaticClock.NOW

    @staticmethod
    def stop_watch():
        return StaticStopWatch()


class StaticStopWatch:
    def start(self):
        pass

    def stop(self):
        pass

    def split_time(self):
        return 0

    def total_time(self):
        return 0


class EsMetricsTests(TestCase):
    TRIAL_TIMESTAMP = datetime.datetime(2016, 1, 31)

    def setUp(self):
        self.cfg = config.Config()
        self.cfg.add(config.Scope.application, "system", "env.name", "unittest")
        self.metrics_store = metrics.EsMetricsStore(self.cfg,
                                                    client_factory_class=MockClientFactory,
                                                    index_template_provider_class=DummyIndexTemplateProvider,
                                                    clock=StaticClock)
        # get hold of the mocked client...
        self.es_mock = self.metrics_store._client
        self.es_mock.exists.return_value = False

    def test_put_value_without_meta_info(self):
        throughput = 5000
        self.metrics_store.open(EsMetricsTests.TRIAL_TIMESTAMP, "test", "append-no-conflicts", "defaults", create=True)
        self.metrics_store.lap = 1

        self.metrics_store.put_count_cluster_level("indexing_throughput", throughput, "docs/s")
        expected_doc = {
            "@timestamp": StaticClock.NOW * 1000,
            "trial-timestamp": "20160131T000000Z",
            "relative-time": 0,
            "environment": "unittest",
            "sample-type": "normal",
            "track": "test",
            "lap": 1,
            "challenge": "append-no-conflicts",
            "car": "defaults",
            "name": "indexing_throughput",
            "value": throughput,
            "unit": "docs/s",
            "meta": {}
        }
        self.metrics_store.close()
        self.es_mock.exists.assert_called_with(index="rally-2016")
        self.es_mock.create_index.assert_called_with(index="rally-2016")
        self.es_mock.bulk_index.assert_called_with(index="rally-2016", doc_type="metrics", items=[expected_doc])

    def test_put_value_with_explicit_timestamps(self):
        throughput = 5000
        self.metrics_store.open(EsMetricsTests.TRIAL_TIMESTAMP, "test", "append-no-conflicts", "defaults", create=True)
        self.metrics_store.lap = 1

        self.metrics_store.put_count_cluster_level(name="indexing_throughput", count=throughput, unit="docs/s",
                                                   absolute_time=0, relative_time=10)
        expected_doc = {
            "@timestamp": 0,
            "trial-timestamp": "20160131T000000Z",
            "relative-time": 10000000,
            "environment": "unittest",
            "sample-type": "normal",
            "track": "test",
            "lap": 1,
            "challenge": "append-no-conflicts",
            "car": "defaults",
            "name": "indexing_throughput",
            "value": throughput,
            "unit": "docs/s",
            "meta": {}
        }
        self.metrics_store.close()
        self.es_mock.exists.assert_called_with(index="rally-2016")
        self.es_mock.create_index.assert_called_with(index="rally-2016")
        self.es_mock.bulk_index.assert_called_with(index="rally-2016", doc_type="metrics", items=[expected_doc])

    def test_put_value_with_meta_info(self):
        throughput = 5000
        # add a user-defined tag
        self.cfg.add(config.Scope.application, "race", "user.tag", "intention:testing")
        self.metrics_store.open(EsMetricsTests.TRIAL_TIMESTAMP, "test", "append-no-conflicts", "defaults", create=True)
        self.metrics_store.lap = 1

        # Ensure we also merge in cluster level meta info
        self.metrics_store.add_meta_info(metrics.MetaInfoScope.cluster, None, "source_revision", "abc123")
        self.metrics_store.add_meta_info(metrics.MetaInfoScope.node, "node0", "os_name", "Darwin")
        self.metrics_store.add_meta_info(metrics.MetaInfoScope.node, "node0", "os_version", "15.4.0")
        # Ensure we separate node level info by node
        self.metrics_store.add_meta_info(metrics.MetaInfoScope.node, "node1", "os_name", "Linux")
        self.metrics_store.add_meta_info(metrics.MetaInfoScope.node, "node1", "os_version", "4.2.0-18-generic")

        self.metrics_store.put_value_node_level("node0", "indexing_throughput", throughput, "docs/s")
        expected_doc = {
            "@timestamp": StaticClock.NOW * 1000,
            "trial-timestamp": "20160131T000000Z",
            "relative-time": 0,
            "environment": "unittest",
            "sample-type": "normal",
            "track": "test",
            "lap": 1,
            "challenge": "append-no-conflicts",
            "car": "defaults",
            "name": "indexing_throughput",
            "value": throughput,
            "unit": "docs/s",
            "meta": {
                "tag_intention": "testing",
                "source_revision": "abc123",
                "os_name": "Darwin",
                "os_version": "15.4.0"
            }
        }
        self.metrics_store.close()
        self.es_mock.exists.assert_called_with(index="rally-2016")
        self.es_mock.create_index.assert_called_with(index="rally-2016")
        self.es_mock.bulk_index.assert_called_with(index="rally-2016", doc_type="metrics", items=[expected_doc])

    def test_get_value(self):
        throughput = 5000
        search_result = {
            "hits": {
                "total": 1,
                "hits": [
                    {
                        "_source": {
                            "@timestamp": StaticClock.NOW * 1000,
                            "value": throughput
                        }
                    }
                ]
            }
        }
        self.es_mock.search = mock.MagicMock(return_value=search_result)

        self.metrics_store.open(EsMetricsTests.TRIAL_TIMESTAMP, "test", "append-no-conflicts", "defaults")

        expected_query = {
            "query": {
                "bool": {
                    "filter": [
                        {
                            "term": {
                                "trial-timestamp": "20160131T000000Z"
                            }
                        },
                        {
                            "term": {
                                "environment": "unittest"
                            }
                        },
                        {
                            "term": {
                                "track": "test"
                            }
                        },
                        {
                            "term": {
                                "challenge": "append-no-conflicts"
                            }
                        },
                        {
                            "term": {
                                "car": "defaults"
                            }
                        },
                        {
                            "term": {
                                "name": "indexing_throughput"
                            }
                        },
                        {
                            "term": {
                                "lap": 3
                            }
                        }
                    ]
                }
            }
        }

        actual_throughput = self.metrics_store.get_one("indexing_throughput", lap=3)

        self.es_mock.search.assert_called_with(index="rally-2016", doc_type="metrics", body=expected_query)

        self.assertEqual(throughput, actual_throughput)

    def test_get_median(self):
        median_throughput = 30535
        search_result = {
            "hits": {
                "total": 1,
            },
            "aggregations": {
                "percentile_stats": {
                    "values": {
                        "50.0": median_throughput
                    }
                }
            }
        }
        self.es_mock.search = mock.MagicMock(return_value=search_result)

        self.metrics_store.open(EsMetricsTests.TRIAL_TIMESTAMP, "test", "append-no-conflicts", "defaults")

        expected_query = {
            "query": {
                "bool": {
                    "filter": [
                        {
                            "term": {
                                "trial-timestamp": "20160131T000000Z"
                            }
                        },
                        {
                            "term": {
                                "environment": "unittest"
                            }
                        },
                        {
                            "term": {
                                "track": "test"
                            }
                        },
                        {
                            "term": {
                                "challenge": "append-no-conflicts"
                            }
                        },
                        {
                            "term": {
                                "car": "defaults"
                            }
                        },
                        {
                            "term": {
                                "name": "indexing_throughput"
                            }
                        },
                        {
                            "term": {
                                "lap": 3
                            }
                        }
                    ]
                }
            },
            "aggs": {
                "percentile_stats": {
                    "percentiles": {
                        "field": "value",
                        "percents": ["50.0"]
                    }
                }
            }
        }

        actual_median_throughput = self.metrics_store.get_median("indexing_throughput", lap=3)

        self.es_mock.search.assert_called_with(index="rally-2016", doc_type="metrics", body=expected_query)

        self.assertEqual(median_throughput, actual_median_throughput)


class EsRaceStoreTests(TestCase):
    TRIAL_TIMESTAMP = datetime.datetime(2016, 1, 31)

    def setUp(self):
        self.cfg = config.Config()
        self.cfg.add(config.Scope.application, "system", "env.name", "unittest-env")
        self.cfg.add(config.Scope.application, "system", "time.start", EsRaceStoreTests.TRIAL_TIMESTAMP)
        self.race_store = metrics.EsRaceStore(self.cfg,
                                              client_factory_class=MockClientFactory,
                                              index_template_provider_class=DummyIndexTemplateProvider,
                                              )
        # get hold of the mocked client...
        self.es_mock = self.race_store.client

    def test_store_race(self):
        self.cfg.add(config.Scope.application, "race", "pipeline", "unittest-pipeline")
        self.cfg.add(config.Scope.application, "race", "user.tag", "")
        self.cfg.add(config.Scope.application, "track", "challenge.name", "index-and-search")
        self.cfg.add(config.Scope.application, "mechanic", "car.name", "defaults")
        self.cfg.add(config.Scope.application, "race", "laps", 1)
        self.cfg.add(config.Scope.application, "launcher", "external.target.hosts", [{"host": "localhost", "port": "9200"}])
        self.cfg.add(config.Scope.application, "mechanic", "source.revision", "latest")
        self.cfg.add(config.Scope.application, "mechanic", "distribution.version", "5.0.0")

        index = "tests"
        type = "test-type"

        schedule = [
            track.Task(track.Operation("index", track.OperationType.Index, None)),
            track.Task(track.Operation("search-all", track.OperationType.Search, None)),
        ]

        t = track.Track(name="unittest", short_description="unittest track", description="unittest track",
                        source_root_url="http://example.org",
                        indices=[track.Index(name=index, auto_managed=True, types=[track.Type(name=type, mapping_file=None)])],
                        challenges=[
                            track.Challenge(name="index-and-search", description="Index & Search", index_settings=None, schedule=schedule)
                        ])
        self.race_store.store_race(t)

        expected_doc = {
            "environment": "unittest-env",
            "trial-timestamp": "20160131T000000Z",
            "pipeline": "unittest-pipeline",
            "revision": "latest",
            "distribution-version": "5.0.0",
            "track": "unittest",
            "laps": 1,
            "selected-challenge": {
                "name": "index-and-search",
                "operations": [
                    "index",
                    "search-all"
                ]
            },
            "car": "defaults",
            "target-hosts": ["localhost:9200"],
            "user-tag": ""
        }

        self.es_mock.index.assert_called_with(index="rally-2016", doc_type="races", item=expected_doc)


class InMemoryMetricsStoreTests(TestCase):
    def setUp(self):
        self.cfg = config.Config()
        self.cfg.add(config.Scope.application, "system", "env.name", "unittest")
        self.metrics_store = metrics.InMemoryMetricsStore(self.cfg, clock=StaticClock)

    def tearDown(self):
        del self.metrics_store
        del self.cfg

    def test_get_value(self):
        throughput = 5000
        self.metrics_store.open(EsMetricsTests.TRIAL_TIMESTAMP, "test", "append-no-conflicts", "defaults", create=True)
        self.metrics_store.lap = 1
        self.metrics_store.put_count_cluster_level("indexing_throughput", 1, "docs/s", sample_type=metrics.SampleType.Warmup)
        self.metrics_store.put_count_cluster_level("indexing_throughput", throughput, "docs/s")
        self.metrics_store.put_count_cluster_level("final_index_size", 1000, "GB")

        self.metrics_store.close()

        self.metrics_store.open(EsMetricsTests.TRIAL_TIMESTAMP, "test", "append-no-conflicts", "defaults")

        self.assertEqual(1, self.metrics_store.get_one("indexing_throughput", sample_type=metrics.SampleType.Warmup))
        self.assertEqual(throughput, self.metrics_store.get_one("indexing_throughput", sample_type=metrics.SampleType.Normal))

    def test_get_percentile(self):
        self.metrics_store.open(EsMetricsTests.TRIAL_TIMESTAMP, "test", "append-no-conflicts", "defaults", create=True)
        self.metrics_store.lap = 1
        for i in range(1, 1001):
            self.metrics_store.put_value_cluster_level("query_latency", float(i), "ms")

        self.metrics_store.close()

        self.metrics_store.open(EsMetricsTests.TRIAL_TIMESTAMP, "test", "append-no-conflicts", "defaults")

        self.assert_equal_percentiles("query_latency", [100.0], {100.0: 1000.0})
        self.assert_equal_percentiles("query_latency", [99.0], {99.0: 990.0})
        self.assert_equal_percentiles("query_latency", [99.9], {99.9: 999.0})
        self.assert_equal_percentiles("query_latency", [0.0], {0.0: 1.0})

        self.assert_equal_percentiles("query_latency", [99, 99.9, 100], {99: 990.0, 99.9: 999.0, 100: 1000.0})

    def test_get_median(self):
        self.metrics_store.open(EsMetricsTests.TRIAL_TIMESTAMP, "test", "append-no-conflicts", "defaults", create=True)
        self.metrics_store.lap = 1
        for i in range(1, 1001):
            self.metrics_store.put_value_cluster_level("query_latency", float(i), "ms")

        self.metrics_store.close()

        self.metrics_store.open(EsMetricsTests.TRIAL_TIMESTAMP, "test", "append-no-conflicts", "defaults")

        self.assertAlmostEqual(500.5, self.metrics_store.get_median("query_latency", lap=1))

    def assert_equal_percentiles(self, name, percentiles, expected_percentiles):
        actual_percentiles = self.metrics_store.get_percentiles(name, percentiles=percentiles)
        self.assertEqual(len(expected_percentiles), len(actual_percentiles))
        for percentile, actual_percentile_value in actual_percentiles.items():
            self.assertAlmostEqual(expected_percentiles[percentile], actual_percentile_value, places=1,
                                   msg=str(percentile) + "th percentile differs")

    def test_externalize_and_bulk_add(self):
        self.metrics_store.open(EsMetricsTests.TRIAL_TIMESTAMP, "test", "append-no-conflicts", "defaults", create=True)
        self.metrics_store.lap = 1
        self.metrics_store.put_count_cluster_level("final_index_size", 1000, "GB")

        self.assertEqual(1, len(self.metrics_store.docs))
        memento = self.metrics_store.to_externalizable()

        self.metrics_store.close()
        del self.metrics_store

        self.metrics_store = metrics.InMemoryMetricsStore(self.cfg, clock=StaticClock)
        self.assertEqual(0, len(self.metrics_store.docs))

        self.metrics_store.bulk_add(memento)
        self.assertEqual(1, len(self.metrics_store.docs))
        self.assertEqual(1000, self.metrics_store.get_one("final_index_size"))
