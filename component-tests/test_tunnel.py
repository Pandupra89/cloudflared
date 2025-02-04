#!/usr/bin/env python
import requests
from conftest import CfdModes
from constants import METRICS_PORT, MAX_RETRIES, BACKOFF_SECS
from retrying import retry
from cli import CloudflaredCli
from util import LOGGER, write_config, start_cloudflared, wait_tunnel_ready, send_requests
import platform

class TestTunnel:
    '''Test tunnels with no ingress rules from config.yaml but ingress rules from CLI only'''

    def test_tunnel_hello_world(self, tmp_path, component_tests_config):
        config = component_tests_config(cfd_mode=CfdModes.NAMED, run_proxy_dns=False, provide_ingress=False)
        LOGGER.debug(config)
        with start_cloudflared(tmp_path, config, cfd_pre_args=["tunnel", "--ha-connections", "1"],  cfd_args=["run", "--hello-world"], new_process=True):
            wait_tunnel_ready(tunnel_url=config.get_url(),
                              require_min_connections=1)

    """
        test_get_host_details does the following:
        1. It gets a management token from Tunnelstore using cloudflared tail token <tunnel_id>
        2. It gets the connector_id after starting a cloudflare tunnel
        3. It sends a request to the management host with the connector_id and management token
        4. Asserts that the response has a hostname and ip.
    """
    def test_get_host_details(self, tmp_path, component_tests_config):
        # TUN-7377 : wait_tunnel_ready does not work properly in windows.
        # Skipping this test for windows for now and will address it as part of tun-7377
        if platform.system() == "Windows":
            return
        config = component_tests_config(cfd_mode=CfdModes.NAMED, run_proxy_dns=False, provide_ingress=False)
        LOGGER.debug(config)
        headers = {}
        headers["Content-Type"] = "application/json"
        config_path = write_config(tmp_path, config.full_config)
        with start_cloudflared(tmp_path, config, cfd_pre_args=["tunnel", "--ha-connections", "1", "--label" , "test"], cfd_args=["run", "--hello-world"], new_process=True):
            wait_tunnel_ready(tunnel_url=config.get_url(),
                              require_min_connections=1)
            cfd_cli = CloudflaredCli(config, config_path, LOGGER)
            connector_id = cfd_cli.get_connector_id(config)[0]
            url = cfd_cli.get_management_url("host_details", config, config_path)
            resp = send_request(url, headers=headers)
            
            # Assert response json.
            assert resp.status_code == 200, "Expected cloudflared to return 200 for host details"
            assert resp.json()["hostname"] == "custom:test", "Expected cloudflared to return hostname"
            assert resp.json()["ip"] != "", "Expected cloudflared to return ip"
            assert resp.json()["connector_id"] == connector_id, "Expected cloudflared to return connector_id"

    
    def test_tunnel_url(self, tmp_path, component_tests_config):
        config = component_tests_config(cfd_mode=CfdModes.NAMED, run_proxy_dns=False, provide_ingress=False)
        LOGGER.debug(config)
        with start_cloudflared(tmp_path, config, cfd_pre_args=["tunnel", "--ha-connections", "1"],  cfd_args=["run", "--url", f"http://localhost:{METRICS_PORT}/"], new_process=True):
            wait_tunnel_ready(require_min_connections=1)
            send_requests(config.get_url()+"/ready", 3, True)

    def test_tunnel_no_ingress(self, tmp_path, component_tests_config):
        '''
        Running a tunnel with no ingress rules provided from either config.yaml or CLI will still work but return 503
        for all incoming requests.
        '''
        config = component_tests_config(cfd_mode=CfdModes.NAMED, run_proxy_dns=False, provide_ingress=False)
        LOGGER.debug(config)
        with start_cloudflared(tmp_path, config, cfd_pre_args=["tunnel", "--ha-connections", "1"],  cfd_args=["run"], new_process=True):
            wait_tunnel_ready(require_min_connections=1)
            resp = send_request(config.get_url()+"/")
            assert resp.status_code == 503, "Expected cloudflared to return 503 for all requests with no ingress defined"
            resp = send_request(config.get_url()+"/test")
            assert resp.status_code == 503, "Expected cloudflared to return 503 for all requests with no ingress defined"


@retry(stop_max_attempt_number=MAX_RETRIES, wait_fixed=BACKOFF_SECS * 1000)
def send_request(url, headers={}):
    with requests.Session() as s:
        return s.get(url, timeout=BACKOFF_SECS, headers=headers)
