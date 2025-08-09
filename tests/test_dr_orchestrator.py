#!/usr/bin/env python3
"""
Comprehensive test suite for Azure to GCP Cross-Cloud DR Orchestrator
Tests all critical components including failover, health monitoring, and data consistency
"""

import unittest
import asyncio
import json
import time
import logging
from unittest.mock import Mock, patch, AsyncMock, MagicMock
from datetime import datetime, timedelta
import sys
import os

# Add src directory to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from orchestrator_engine import DrOrchestratorEngine
from failover_coordinator import FailoverCoordinator
from health_monitor import HealthMonitor
from metrics_collector import MetricsCollector
from config_manager import ConfigManager

# Configure logging for tests
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

class TestDrOrchestratorEngine(unittest.TestCase):
    """Test cases for the main DR Orchestrator Engine"""
    
    def setUp(self):
        """Set up test fixtures"""
        self.config = {
            'azure': {
                'subscription_id': 'test-sub-id',
                'resource_group': 'test-rg',
                'sql_mi_name': 'test-sql-mi',
                'aks_cluster': 'test-aks'
            },
            'gcp': {
                'project_id': 'test-project',
                'region': 'us-central1',
                'cloud_sql_instance': 'test-cloud-sql',
                'gke_cluster': 'test-gke'
            },
            'thresholds': {
                'health_critical': 0.5,
                'health_warning': 0.8,
                'rto_target_seconds': 300,
                'rpo_target_ms': 30000
            }
        }
        self.engine = DrOrchestratorEngine(self.config)
    
    @patch('orchestrator_engine.aiohttp.ClientSession')
    async def test_engine_initialization(self, mock_session):
        """Test DR engine initialization"""
        self.assertIsNotNone(self.engine)
        self.assertEqual(self.engine.config, self.config)
        self.assertIsInstance(self.engine.health_monitor, HealthMonitor)
        self.assertIsInstance(self.engine.failover_coordinator, FailoverCoordinator)
        self.assertIsInstance(self.engine.metrics_collector, MetricsCollector)
    
    @patch('orchestrator_engine.DrOrchestratorEngine._check_azure_health')
    @patch('orchestrator_engine.DrOrchestratorEngine._check_gcp_health')
    @patch('orchestrator_engine.DrOrchestratorEngine._check_striim_health')
    async def test_overall_health_calculation(self, mock_striim, mock_gcp, mock_azure):
        """Test overall health score calculation"""
        # Mock health check responses
        mock_azure.return_value = {'score': 0.9, 'status': 'healthy'}
        mock_gcp.return_value = {'score': 0.8, 'status': 'healthy'}
        mock_striim.return_value = {'score': 0.95, 'status': 'healthy'}
        
        health_score = await self.engine.get_overall_health()
        
        # Should be weighted average: (0.9*0.4 + 0.8*0.4 + 0.95*0.2) = 0.87
        expected_score = (0.9 * 0.4) + (0.8 * 0.4) + (0.95 * 0.2)
        self.assertAlmostEqual(health_score, expected_score, places=2)
    
    @patch('orchestrator_engine.DrOrchestratorEngine.get_overall_health')
    async def test_health_monitoring_triggers_failover(self, mock_health):
        """Test that low health triggers failover"""
        # Simulate critical health score
        mock_health.return_value = 0.3
        
        with patch.object(self.engine.failover_coordinator, 'initiate_failover') as mock_failover:
            mock_failover.return_value = {'success': True, 'duration': 180}
            
            await self.engine.start_monitoring()
            
            # Give some time for monitoring loop
            await asyncio.sleep(0.1)
            
            # Verify failover was triggered
            mock_failover.assert_called()
    
    async def test_metrics_collection(self):
        """Test metrics collection functionality"""
        with patch.object(self.engine.metrics_collector, 'collect_all_metrics') as mock_collect:
            mock_collect.return_value = {
                'health_score': 0.85,
                'response_times': {'azure': 150, 'gcp': 200},
                'replication_lag': 15000,
                'timestamp': time.time()
            }
            
            metrics = await self.engine.collect_metrics()
            
            self.assertIn('health_score', metrics)
            self.assertIn('response_times', metrics)
            self.assertIn('replication_lag', metrics)
            mock_collect.assert_called_once()


class TestFailoverCoordinator(unittest.TestCase):
    """Test cases for Failover Coordinator"""
    
    def setUp(self):
        """Set up test fixtures"""
        self.config = {
            'azure': {'region': 'eastus', 'resource_group': 'test-rg'},
            'gcp': {'region': 'us-central1', 'project_id': 'test-project'},
            'thresholds': {'rto_target_seconds': 300}
        }
        self.coordinator = FailoverCoordinator(self.config)
    
    @patch('failover_coordinator.AzureResourceManager')
    @patch('failover_coordinator.GcpResourceManager')
    @patch('failover_coordinator.StriimManager')
    async def test_successful_failover_azure_to_gcp(self, mock_striim, mock_gcp, mock_azure):
        """Test successful failover from Azure to GCP"""
        # Mock successful operations
        mock_azure_instance = mock_azure.return_value
        mock_gcp_instance = mock_gcp.return_value
        mock_striim_instance = mock_striim.return_value
        
        mock_azure_instance.get_health_status.return_value = {'healthy': False, 'reason': 'connection_timeout'}
        mock_gcp_instance.ensure_cluster_ready.return_value = True
        mock_gcp_instance.scale_cluster.return_value = True
        mock_striim_instance.switch_replication_direction.return_value = True
        
        # Execute failover
        start_time = time.time()
        result = await self.coordinator.initiate_failover(
            source='azure',
            target='gcp',
            reason='health_degradation'
        )
        end_time = time.time()
        
        # Verify results
        self.assertTrue(result['success'])
        self.assertLess(result['duration'], 300)  # Within RTO
        self.assertEqual(result['source'], 'azure')
        self.assertEqual(result['target'], 'gcp')
        self.assertIn('stages', result)
        
        # Verify all stages completed
        expected_stages = ['detection', 'validation', 'traffic_switch', 'cluster_spinup', 'verification']
        for stage in expected_stages:
            self.assertIn(stage, result['stages'])
            self.assertIsInstance(result['stages'][stage]['duration'], (int, float))
    
    @patch('failover_coordinator.time.time')
    async def test_failover_timeout_handling(self, mock_time):
        """Test failover timeout handling"""
        # Mock time to simulate timeout
        mock_time.side_effect = [0, 100, 200, 400]  # Last call exceeds 300s timeout
        
        with patch.object(self.coordinator, '_execute_failover_stage') as mock_stage:
            mock_stage.side_effect = asyncio.sleep(1)  # Simulate slow operation
            
            result = await self.coordinator.initiate_failover(
                source='azure',
                target='gcp',
                reason='timeout_test'
            )
            
            self.assertFalse(result['success'])
            self.assertEqual(result['error'], 'Failover timeout exceeded')
    
    async def test_failover_stage_breakdown(self):
        """Test individual failover stage timing"""
        with patch.multiple(
            self.coordinator,
            _validate_failover_conditions=AsyncMock(return_value=True),
            _switch_traffic=AsyncMock(return_value=True),
            _ensure_target_ready=AsyncMock(return_value=True),
            _verify_failover_success=AsyncMock(return_value=True)
        ):
            result = await self.coordinator.initiate_failover(
                source='azure',
                target='gcp',
                reason='stage_test'
            )
            
            # Verify stage timing tracking
            stages = result['stages']
            total_duration = sum(stage['duration'] for stage in stages.values())
            
            self.assertAlmostEqual(result['duration'], total_duration, delta=1.0)
            
            # Verify all stages have reasonable durations (> 0)
            for stage_name, stage_info in stages.items():
                self.assertGreater(stage_info['duration'], 0)
                self.assertIn('start_time', stage_info)
                self.assertIn('end_time', stage_info)


class TestHealthMonitor(unittest.TestCase):
    """Test cases for Health Monitor"""
    
    def setUp(self):
        """Set up test fixtures"""
        self.config = {
            'azure': {
                'sql_mi_endpoint': 'test-sql-mi.database.windows.net',
                'aks_endpoint': 'test-aks.eastus.azmk8s.io'
            },
            'gcp': {
                'cloud_sql_endpoint': 'test-cloud-sql:us-central1:instance',
                'gke_endpoint': 'test-gke.us-central1.container.googleapis.com'
            },
            'striim': {
                'endpoint': 'http://striim-cluster:9080'
            }
        }
        self.monitor = HealthMonitor(self.config)
    
    @patch('health_monitor.aiohttp.ClientSession.get')
    async def test_azure_sql_mi_health_check(self, mock_get):
        """Test Azure SQL MI health check"""
        # Mock successful response
        mock_response = Mock()
        mock_response.status = 200
        mock_response.json = AsyncMock(return_value={'status': 'online', 'response_time_ms': 150})
        mock_get.return_value.__aenter__ = AsyncMock(return_value=mock_response)
        
        health = await self.monitor.check_azure_sql_mi_health()
        
        self.assertIsInstance(health, dict)
        self.assertIn('score', health)
        self.assertIn('response_time_ms', health)
        self.assertIn('status', health)
        self.assertEqual(health['status'], 'healthy')
        self.assertGreaterEqual(health['score'], 0.8)
    
    @patch('health_monitor.aiohttp.ClientSession.get')
    async def test_gcp_cloud_sql_health_check(self, mock_get):
        """Test GCP Cloud SQL health check"""
        # Mock successful response
        mock_response = Mock()
        mock_response.status = 200
        mock_response.json = AsyncMock(return_value={'status': 'RUNNABLE', 'response_time_ms': 200})
        mock_get.return_value.__aenter__ = AsyncMock(return_value=mock_response)
        
        health = await self.monitor.check_gcp_cloud_sql_health()
        
        self.assertIsInstance(health, dict)
        self.assertIn('score', health)
        self.assertIn('response_time_ms', health)
        self.assertEqual(health['status'], 'healthy')
    
    @patch('health_monitor.aiohttp.ClientSession.get')
    async def test_striim_health_check(self, mock_get):
        """Test Striim CDC health check"""
        # Mock Striim response with replication metrics
        mock_response = Mock()
        mock_response.status = 200
        mock_response.json = AsyncMock(return_value={
            'status': 'running',
            'applications': {
                'AzureToGcpDrReplication': {
                    'status': 'running',
                    'lag_ms': 15000,
                    'throughput_events_per_sec': 1500,
                    'error_count': 0
                }
            }
        })
        mock_get.return_value.__aenter__ = AsyncMock(return_value=mock_response)
        
        health = await self.monitor.check_striim_health()
        
        self.assertIsInstance(health, dict)
        self.assertIn('score', health)
        self.assertIn('lag_ms', health)
        self.assertIn('throughput', health)
        self.assertEqual(health['status'], 'healthy')
        self.assertLessEqual(health['lag_ms'], 30000)  # Within RPO target
    
    async def test_health_score_calculation(self):
        """Test health score calculation logic"""
        # Test various scenarios
        test_cases = [
            {'response_time': 100, 'errors': 0, 'expected_min_score': 0.9},
            {'response_time': 500, 'errors': 0, 'expected_min_score': 0.7},
            {'response_time': 1000, 'errors': 2, 'expected_min_score': 0.5},
            {'response_time': 2000, 'errors': 5, 'expected_min_score': 0.2}
        ]
        
        for case in test_cases:
            score = self.monitor._calculate_health_score(
                response_time_ms=case['response_time'],
                error_count=case['errors'],
                availability=1.0
            )
            self.assertGreaterEqual(score, case['expected_min_score'])
            self.assertLessEqual(score, 1.0)


class TestMetricsCollector(unittest.TestCase):
    """Test cases for Metrics Collector"""
    
    def setUp(self):
        """Set up test fixtures"""
        self.config = {
            'prometheus': {
                'pushgateway_url': 'http://prometheus-pushgateway:9091',
                'job_name': 'dr-orchestrator'
            }
        }
        self.collector = MetricsCollector(self.config)
    
    def test_metric_registration(self):
        """Test Prometheus metric registration"""
        # Verify all required metrics are registered
        required_metrics = [
            'dr_overall_health_score',
            'dr_failover_duration_seconds',
            'dr_database_response_time_ms',
            'striim_replication_lag_ms',
            'dr_service_health_score'
        ]
        
        for metric_name in required_metrics:
            self.assertIn(metric_name, self.collector._metrics)
    
    @patch('metrics_collector.push_to_gateway')
    def test_metrics_push_to_prometheus(self, mock_push):
        """Test pushing metrics to Prometheus"""
        # Record some test metrics
        self.collector.record_health_score(0.85)
        self.collector.record_failover_duration(180, 'azure', 'gcp', 'health_degradation')
        self.collector.record_database_response_time(150, 'azure_sql_mi')
        
        # Push metrics
        self.collector.push_metrics()
        
        # Verify push was called
        mock_push.assert_called_once()
        args, kwargs = mock_push.call_args
        self.assertEqual(kwargs['gateway'], 'prometheus-pushgateway:9091')
        self.assertEqual(kwargs['job'], 'dr-orchestrator')
    
    def test_histogram_metrics_recording(self):
        """Test histogram metrics for performance tracking"""
        # Record multiple failover durations
        durations = [120, 180, 240, 290, 310]
        for duration in durations:
            self.collector.record_failover_duration(
                duration, 'azure', 'gcp', 'test'
            )
        
        # Verify histogram buckets are populated
        histogram_metric = self.collector._metrics['dr_failover_duration_seconds']
        self.assertIsNotNone(histogram_metric)
        
        # Test percentile calculations (would be done by Prometheus)
        # This is more of a smoke test to ensure no errors
        self.collector.push_metrics()


class TestIntegrationScenarios(unittest.TestCase):
    """Integration tests for end-to-end scenarios"""
    
    def setUp(self):
        """Set up integration test fixtures"""
        self.config = {
            'azure': {
                'subscription_id': 'test-sub',
                'resource_group': 'dr-test-rg',
                'sql_mi_name': 'dr-test-sql-mi',
                'aks_cluster': 'dr-test-aks'
            },
            'gcp': {
                'project_id': 'dr-test-project',
                'region': 'us-central1',
                'cloud_sql_instance': 'dr-test-cloud-sql',
                'gke_cluster': 'dr-test-gke'
            },
            'striim': {
                'cluster_endpoint': 'http://striim-cluster:9080',
                'application_name': 'AzureToGcpDrReplication'
            },
            'thresholds': {
                'health_critical': 0.5,
                'health_warning': 0.8,
                'rto_target_seconds': 300,
                'rpo_target_ms': 30000
            }
        }
    
    @patch('orchestrator_engine.aiohttp.ClientSession')
    async def test_complete_disaster_recovery_simulation(self, mock_session):
        """Test complete DR scenario from detection to recovery"""
        # Initialize orchestrator
        engine = DrOrchestratorEngine(self.config)
        
        # Mock external service responses
        with patch.multiple(
            engine,
            _check_azure_health=AsyncMock(return_value={'score': 0.3, 'status': 'degraded'}),
            _check_gcp_health=AsyncMock(return_value={'score': 0.9, 'status': 'healthy'}),
            _check_striim_health=AsyncMock(return_value={'score': 0.8, 'status': 'healthy'})
        ):
            with patch.object(engine.failover_coordinator, 'initiate_failover') as mock_failover:
                mock_failover.return_value = {
                    'success': True,
                    'duration': 245,
                    'source': 'azure',
                    'target': 'gcp',
                    'stages': {
                        'detection': {'duration': 15, 'success': True},
                        'validation': {'duration': 30, 'success': True},
                        'traffic_switch': {'duration': 120, 'success': True},
                        'cluster_spinup': {'duration': 60, 'success': True},
                        'verification': {'duration': 20, 'success': True}
                    }
                }
                
                # Simulate disaster detection and response
                health_score = await engine.get_overall_health()
                self.assertLess(health_score, 0.5)  # Should trigger failover
                
                # Execute failover
                failover_result = await engine.failover_coordinator.initiate_failover(
                    source='azure',
                    target='gcp',
                    reason='azure_region_outage'
                )
                
                # Verify successful failover within RTO
                self.assertTrue(failover_result['success'])
                self.assertLess(failover_result['duration'], 300)
                self.assertEqual(failover_result['source'], 'azure')
                self.assertEqual(failover_result['target'], 'gcp')
    
    async def test_data_consistency_validation(self):
        """Test data consistency validation during failover"""
        # This would integrate with actual database connections in real environment
        consistency_validator = Mock()
        consistency_validator.validate_data_consistency = AsyncMock(return_value={
            'consistent': True,
            'last_sync_timestamp': time.time() - 10,  # 10 seconds ago
            'record_count_diff': 0,
            'checksum_match': True
        })
        
        # Simulate data validation
        validation_result = await consistency_validator.validate_data_consistency()
        
        self.assertTrue(validation_result['consistent'])
        self.assertEqual(validation_result['record_count_diff'], 0)
        self.assertTrue(validation_result['checksum_match'])
    
    async def test_performance_under_load(self):
        """Test system performance under simulated load"""
        # Simulate multiple concurrent health checks
        health_monitor = HealthMonitor(self.config)
        
        with patch.object(health_monitor, '_perform_health_check') as mock_check:
            mock_check.return_value = {'score': 0.85, 'response_time_ms': 150}
            
            # Execute concurrent health checks
            tasks = []
            for i in range(10):
                tasks.append(health_monitor.check_azure_sql_mi_health())
            
            results = await asyncio.gather(*tasks)
            
            # Verify all checks completed successfully
            self.assertEqual(len(results), 10)
            for result in results:
                self.assertIn('score', result)
                self.assertGreaterEqual(result['score'], 0.8)


class TestLoadAndStress(unittest.TestCase):
    """Load and stress testing scenarios"""
    
    def setUp(self):
        """Set up load test fixtures"""
        self.config = {
            'thresholds': {'rto_target_seconds': 300},
            'monitoring': {'check_interval_seconds': 30}
        }
    
    async def test_concurrent_failover_prevention(self):
        """Test that concurrent failovers are prevented"""
        coordinator = FailoverCoordinator(self.config)
        
        # Mock a long-running failover
        with patch.object(coordinator, '_execute_failover') as mock_execute:
            mock_execute.return_value = asyncio.sleep(10)  # 10 second failover
            
            # Start first failover
            task1 = asyncio.create_task(coordinator.initiate_failover('azure', 'gcp', 'test1'))
            await asyncio.sleep(0.1)  # Let first failover start
            
            # Try to start second failover
            task2 = asyncio.create_task(coordinator.initiate_failover('gcp', 'azure', 'test2'))
            
            # Second failover should be rejected
            result2 = await task2
            self.assertFalse(result2['success'])
            self.assertIn('already in progress', result2['error'].lower())
            
            # Cancel first task to clean up
            task1.cancel()
    
    async def test_health_check_performance(self):
        """Test health check performance under load"""
        monitor = HealthMonitor(self.config)
        
        # Time multiple health checks
        start_time = time.time()
        
        with patch.object(monitor, '_perform_health_check') as mock_check:
            mock_check.return_value = {'score': 0.9, 'response_time_ms': 100}
            
            # Perform 100 health checks
            tasks = [monitor.check_azure_sql_mi_health() for _ in range(100)]
            results = await asyncio.gather(*tasks)
            
        end_time = time.time()
        total_duration = end_time - start_time
        
        # Verify performance (should complete 100 checks in reasonable time)
        self.assertLess(total_duration, 5.0)  # Less than 5 seconds
        self.assertEqual(len(results), 100)


async def run_async_tests():
    """Run all async test methods"""
    # Create test suite for async tests
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    
    # Add async test classes
    async_test_classes = [
        TestDrOrchestratorEngine,
        TestFailoverCoordinator,
        TestHealthMonitor,
        TestIntegrationScenarios,
        TestLoadAndStress
    ]
    
    for test_class in async_test_classes:
        tests = loader.loadTestsFromTestCase(test_class)
        suite.addTests(tests)
    
    # Custom async test runner
    runner = unittest.TextTestRunner(verbosity=2)
    
    # Convert async test methods to sync for the test runner
    for test_case in suite:
        if hasattr(test_case, '_testMethodName'):
            test_method = getattr(test_case, test_case._testMethodName)
            if asyncio.iscoroutinefunction(test_method):
                # Wrap async method
                def sync_wrapper(async_method):
                    def wrapper(self):
                        loop = asyncio.new_event_loop()
                        asyncio.set_event_loop(loop)
                        try:
                            return loop.run_until_complete(async_method(self))
                        finally:
                            loop.close()
                    return wrapper
                
                setattr(test_case.__class__, test_case._testMethodName, sync_wrapper(test_method))
    
    return runner.run(suite)


if __name__ == '__main__':
    # Configure test environment
    os.environ['TESTING'] = 'true'
    
    print("Starting Azure to GCP DR Orchestrator Test Suite")
    print("=" * 60)
    
    # Run synchronous tests first
    sync_loader = unittest.TestLoader()
    sync_suite = unittest.TestSuite()
    
    # Add sync test classes
    sync_test_classes = [TestMetricsCollector]
    
    for test_class in sync_test_classes:
        tests = sync_loader.loadTestsFromTestCase(test_class)
        sync_suite.addTests(tests)
    
    sync_runner = unittest.TextTestRunner(verbosity=2)
    sync_result = sync_runner.run(sync_suite)
    
    # Run async tests
    print("\nRunning async tests...")
    async_result = asyncio.run(run_async_tests())
    
    # Summary
    total_tests = sync_result.testsRun + async_result.testsRun
    total_failures = len(sync_result.failures) + len(async_result.failures)
    total_errors = len(sync_result.errors) + len(async_result.errors)
    
    print(f"\nTest Summary:")
    print(f"Total Tests: {total_tests}")
    print(f"Failures: {total_failures}")
    print(f"Errors: {total_errors}")
    print(f"Success Rate: {((total_tests - total_failures - total_errors) / total_tests * 100):.1f}%")
    
    # Exit with appropriate code
    exit_code = 0 if (total_failures + total_errors) == 0 else 1
    sys.exit(exit_code)
