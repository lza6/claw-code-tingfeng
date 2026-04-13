"""测试 MetricsCollector — 确保指标采集线程安全和导出功能"""
import threading
import pytest

from src.core.metrics_exporter import (
    MetricsCollector,
    MetricPoint,
    get_metrics_collector,
    reset_metrics_collector,
)


class TestMetricPoint:
    def test_creation(self):
        point = MetricPoint(name='test', value=1.0)
        assert point.name == 'test'
        assert point.value == 1.0
        assert point.labels == {}

    def test_creation_with_labels(self):
        point = MetricPoint(name='test', value=42.0, labels={'env': 'prod'})
        assert point.labels == {'env': 'prod'}


class TestMetricsCollector:
    def setup_method(self):
        self.collector = MetricsCollector()

    def test_increment_counter(self):
        self.collector.increment_counter('requests', 1.0)
        self.collector.increment_counter('requests', 2.0)
        counters = self.collector.get_counters()
        assert counters['requests'] == 3.0

    def test_set_gauge(self):
        self.collector.set_gauge('temperature', 72.5)
        gauges = self.collector.get_gauges()
        assert gauges['temperature'] == 72.5

    def test_observe_histogram(self):
        for v in [1.0, 2.0, 3.0]:
            self.collector.observe_histogram('latency', v)
        histograms = self.collector.get_histograms()
        assert 'latency' in histograms
        assert len(histograms['latency']) == 3

    def test_summary(self):
        self.collector.increment_counter('hits', 5.0)
        for v in [10, 20, 30]:
            self.collector.observe_histogram('duration', v)
        summary = self.collector.get_summary()
        assert summary['counters']['hits'] == 5.0
        assert summary['histograms']['duration']['count'] == 3
        assert summary['histograms']['duration']['avg'] == 20.0

    def test_reset(self):
        self.collector.increment_counter('x', 1.0)
        self.collector.reset()
        assert self.collector.get_counters() == {}
        assert self.collector.get_gauges() == {}
        assert self.collector.get_histograms() == {}

    def test_prometheus_export(self):
        self.collector.increment_counter('total', 42.0)
        output = self.collector.export_prometheus()
        assert 'total' in output
        assert 'counter' in output

    def test_prometheus_export_with_labels(self):
        self.collector.set_gauge('cpu', 80.0, labels={'host': 'server1'})
        output = self.collector.export_prometheus()
        assert 'cpu' in output
        assert 'host' in output

    def test_opentelemetry_export(self):
        self.collector.increment_counter('req', 1.0)
        output = self.collector.export_opentelemetry()
        assert 'resource_metrics' in output
        resource = output['resource_metrics'][0]['resource']
        assert resource['attributes']['service.name'] == 'clawd-code'
        assert resource['attributes']['service.version'] == '0.39.0'

    def test_json_export(self):
        self.collector.set_gauge('mem', 1024.0)
        output = self.collector.export_json()
        assert 'gauges' in output

    def test_make_key_with_labels(self):
        key = MetricsCollector._make_key('test', {'a': '1', 'b': '2'})
        assert 'a=1' in key
        assert 'b=2' in key

    def test_parse_key(self):
        name, labels = MetricsCollector._parse_key('test{a=1,b=2}')
        assert name == 'test'
        assert labels == {'a': '1', 'b': '2'}

    def test_parse_key_no_labels(self):
        name, labels = MetricsCollector._parse_key('simple')
        assert name == 'simple'
        assert labels == {}

    def test_format_labels(self):
        result = MetricsCollector._format_labels({'host': 's1', 'env': 'prod'})
        assert 'host=' in result
        assert 'env=' in result

    def test_format_labels_empty(self):
        assert MetricsCollector._format_labels({}) == ''

    def test_counter_with_labels(self):
        self.collector.increment_counter('errors', 1.0, labels={'code': '500'})
        self.collector.increment_counter('errors', 2.0, labels={'code': '404'})
        counters = self.collector.get_counters()
        assert counters['errors{code=404}'] == 2.0
        assert counters['errors{code=500}'] == 1.0


class TestGlobalCollector:
    def teardown_method(self):
        reset_metrics_collector()

    def test_get_metrics_collector_is_singleton(self):
        a = get_metrics_collector()
        b = get_metrics_collector()
        assert a is b

    def test_reset_replaces_instance(self):
        a = get_metrics_collector()
        reset_metrics_collector()
        b = get_metrics_collector()
        assert a is not b

    def test_thread_safe_initialization(self):
        """并发获取应返回同一个实例"""
        results = []

        def fetch():
            results.append(get_metrics_collector())

        threads = [threading.Thread(target=fetch) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert all(r is results[0] for r in results)

    def test_thread_safety_metrics(self):
        """并发写入不应崩溃或丢失数据"""
        collector = get_metrics_collector()

        def write():
            for i in range(100):
                collector.increment_counter('concurrent', 1.0)

        threads = [threading.Thread(target=write) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        counters = collector.get_counters()
        assert counters.get('concurrent', 0) == 500
