"""
Unit tests for Module E: MQTT Communication Layer & Home Assistant Discovery.
"""

from unittest.mock import MagicMock, patch
import pytest

from fluxem.ingestion.pipeline import IngestionPipeline
from fluxem.mqtt.publisher import MQTTPublisher
from fluxem.optimization.engine import OptimizationEngine


def test_mqtt_publisher_disabled_by_default(sample_payload_dict):
    """Verify that MQTTPublisher does nothing when enabled=False."""
    publisher = MQTTPublisher(enabled=False)
    assert publisher.connect() is False

    pipeline = IngestionPipeline()
    context = pipeline.ingest(sample_payload_dict)
    engine = OptimizationEngine()
    response = engine.optimize(context)

    assert publisher.publish_optimization_result(response) is False
    assert publisher.publish_home_assistant_discovery(["water_heater"]) is False


@patch("paho.mqtt.client.Client")
def test_mqtt_publisher_connect_and_publish(mock_client_class, sample_payload_dict):
    """Verify MQTT connect and full schedule payload publishing."""
    mock_client = MagicMock()
    mock_client_class.return_value = mock_client

    publisher = MQTTPublisher(
        host="192.168.1.100",
        port=1883,
        username="mqtt_user",
        password="secret_password",
        topic_prefix="fluxem_test",
        enabled=True,
    )

    # 1. Connect
    success = publisher.connect()
    assert success is True
    assert publisher._is_connected is True
    mock_client.username_pw_set.assert_called_with("mqtt_user", "secret_password")
    mock_client.connect.assert_called_with("192.168.1.100", 1883, keepalive=60)
    mock_client.loop_start.assert_called_once()

    # 2. Publish Optimization Results
    pipeline = IngestionPipeline()
    context = pipeline.ingest(sample_payload_dict)
    engine = OptimizationEngine()
    response = engine.optimize(context)

    publish_success = publisher.publish_optimization_result(response)
    assert publish_success is True

    # Verify published topics
    published_topics = [call[0][0] for call in mock_client.publish.call_args_list]
    assert "fluxem_test/status" in published_topics
    assert "fluxem_test/summary" in published_topics
    assert "fluxem_test/timestamps" in published_topics
    assert "fluxem_test/deferrable_loads/water_heater/power_curve" in published_topics
    assert "fluxem_test/deferrable_loads/water_heater/state" in published_topics
    assert "fluxem_test/battery/power_curve" in published_topics
    assert "fluxem_test/battery/soc_curve" in published_topics
    assert "fluxem_test/grid/import_power_curve" in published_topics

    # 3. Publish Home Assistant Discovery
    discovery_success = publisher.publish_home_assistant_discovery(["water_heater", "pool_pump"])
    assert discovery_success is True

    discovery_topics = [call[0][0] for call in mock_client.publish.call_args_list if "homeassistant/" in call[0][0]]
    assert "homeassistant/sensor/fluxem_test/status/config" in discovery_topics
    assert "homeassistant/binary_sensor/fluxem_test/water_heater_state/config" in discovery_topics
    assert "homeassistant/sensor/fluxem_test/battery_target_power/config" in discovery_topics

    # 4. Disconnect
    publisher.disconnect()
    mock_client.loop_stop.assert_called_once()
    mock_client.disconnect.assert_called_once()


def test_mqtt_test_broker_connection():
    """Verify test_broker_connection helper with mocked MQTT client."""
    with patch("paho.mqtt.client.Client") as mock_client_class:
        mock_client = MagicMock()
        mock_client_class.return_value = mock_client

        def fake_connect(host, port, keepalive):
            # simulate triggering on_connect callback
            if mock_client.on_connect:
                mock_client.on_connect(mock_client, None, {}, 0)

        mock_client.connect.side_effect = fake_connect

        success, msg = MQTTPublisher.test_broker_connection("192.168.1.50", 1883)
        assert success is True
        assert "Successfully connected" in msg


@pytest.mark.asyncio
async def test_api_test_mqtt_connection_endpoint(async_client):
    """Verify /api/v1/mqtt/test-connection endpoint."""
    with patch("fluxem.mqtt.publisher.MQTTPublisher.test_broker_connection") as mock_test:
        mock_test.return_value = (True, "Successfully connected to MQTT broker at 10.0.0.123:1883")

        response = await async_client.post(
            "/api/v1/mqtt/test-connection",
            json={"mqtt_broker_host": "10.0.0.123", "mqtt_broker_port": 1883},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["connected"] is True
        assert "Successfully connected" in data["message"]

