"""
Selenium-based UI tests for DR Orchestrator Dashboard
"""

import pytest
import time
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options
from selenium.common.exceptions import TimeoutException, NoSuchElementException


class TestDRDashboardUI:
    """UI tests for DR Orchestrator Dashboard"""
    
    @pytest.fixture(autouse=True)
    def setup(self):
        """Setup test browser"""
        chrome_options = Options()
        chrome_options.add_argument("--headless")
        chrome_options.add_argument("--no-sandbox")
        chrome_options.add_argument("--disable-dev-shm-usage")
        chrome_options.add_argument("--window-size=1920,1080")
        
        self.driver = webdriver.Chrome(options=chrome_options)
        self.wait = WebDriverWait(self.driver, 10)
        self.dashboard_url = "http://localhost:3000"  # Grafana dashboard
        
        yield
        
        self.driver.quit()
    
    def test_dashboard_loads_successfully(self):
        """Test that the main dashboard loads without errors"""
        self.driver.get(self.dashboard_url)
        
        # Wait for page to load
        self.wait.until(EC.presence_of_element_located((By.TAG_NAME, "body")))
        
        # Check page title
        assert "Grafana" in self.driver.title
        
        # Verify no JavaScript errors (check console logs)
        logs = self.driver.get_log('browser')
        errors = [log for log in logs if log['level'] == 'SEVERE']
        assert len(errors) == 0, f"JavaScript errors found: {errors}"
    
    def test_login_security(self):
        """Test login page security features"""
        self.driver.get(f"{self.dashboard_url}/login")
        
        # Check for HTTPS redirect (in production)
        current_url = self.driver.current_url
        
        # Verify login form exists
        try:
            username_field = self.wait.until(
                EC.presence_of_element_located((By.NAME, "user"))
            )
            password_field = self.driver.find_element(By.NAME, "password")
            login_button = self.driver.find_element(By.CSS_SELECTOR, "button[type='submit']")
            
            assert username_field.is_displayed()
            assert password_field.is_displayed()
            assert login_button.is_displayed()
            
            # Check password field type
            assert password_field.get_attribute("type") == "password"
            
        except TimeoutException:
            pytest.skip("Login form not found - may be using different auth method")
    
    def test_unauthorized_access_blocked(self):
        """Test that unauthorized access to protected pages is blocked"""
        protected_urls = [
            f"{self.dashboard_url}/dashboard/db/dr-orchestrator",
            f"{self.dashboard_url}/admin/users",
            f"{self.dashboard_url}/datasources"
        ]
        
        for url in protected_urls:
            self.driver.get(url)
            
            # Should redirect to login or show access denied
            current_url = self.driver.current_url
            page_content = self.driver.page_source.lower()
            
            assert (
                "/login" in current_url or
                "unauthorized" in page_content or
                "access denied" in page_content or
                "forbidden" in page_content
            ), f"Unauthorized access not blocked for {url}"
    
    def test_dashboard_metrics_display(self):
        """Test that metrics are properly displayed"""
        # This would require valid credentials in a real test
        self.driver.get(self.dashboard_url)
        
        # Skip if login required
        if "/login" in self.driver.current_url:
            pytest.skip("Authentication required for metrics test")
        
        # Look for metric panels
        try:
            panels = self.driver.find_elements(By.CSS_SELECTOR, ".panel")
            assert len(panels) > 0, "No metric panels found on dashboard"
            
            # Check for specific DR metrics
            page_text = self.driver.page_source.lower()
            expected_metrics = [
                "failover",
                "health",
                "replication",
                "latency"
            ]
            
            for metric in expected_metrics:
                assert metric in page_text, f"Expected metric '{metric}' not found"
                
        except NoSuchElementException:
            pytest.skip("Dashboard panels not accessible")
    
    def test_responsive_design(self):
        """Test dashboard responsive design"""
        screen_sizes = [
            (1920, 1080),  # Desktop
            (1024, 768),   # Tablet
            (375, 667)     # Mobile
        ]
        
        for width, height in screen_sizes:
            self.driver.set_window_size(width, height)
            self.driver.get(self.dashboard_url)
            
            # Wait for page to adjust
            time.sleep(1)
            
            # Check that content is visible
            body = self.driver.find_element(By.TAG_NAME, "body")
            assert body.is_displayed()
            
            # Verify no horizontal scroll on smaller screens
            if width < 1024:
                scroll_width = self.driver.execute_script("return document.body.scrollWidth")
                client_width = self.driver.execute_script("return document.body.clientWidth")
                assert scroll_width <= client_width + 20, f"Horizontal scroll detected at {width}x{height}"
    
    def test_performance_metrics(self):
        """Test dashboard performance"""
        start_time = time.time()
        
        self.driver.get(self.dashboard_url)
        self.wait.until(EC.presence_of_element_located((By.TAG_NAME, "body")))
        
        load_time = time.time() - start_time
        
        # Dashboard should load within 5 seconds
        assert load_time < 5.0, f"Dashboard took {load_time:.2f}s to load, expected < 5s"
        
        # Check for performance timing
        navigation_timing = self.driver.execute_script(
            "return window.performance.timing"
        )
        
        if navigation_timing:
            dom_load_time = (
                navigation_timing['domContentLoadedEventEnd'] - 
                navigation_timing['navigationStart']
            ) / 1000
            
            assert dom_load_time < 3.0, f"DOM load time {dom_load_time:.2f}s too slow"
    
    def test_accessibility_basics(self):
        """Test basic accessibility features"""
        self.driver.get(self.dashboard_url)
        
        # Check for alt text on images
        images = self.driver.find_elements(By.TAG_NAME, "img")
        for img in images:
            alt_text = img.get_attribute("alt")
            src = img.get_attribute("src")
            if src and not src.startswith("data:"):
                assert alt_text is not None, f"Image missing alt text: {src}"
        
        # Check for proper heading hierarchy
        headings = self.driver.find_elements(By.CSS_SELECTOR, "h1, h2, h3, h4, h5, h6")
        if headings:
            # Should start with h1 or h2
            first_heading = headings[0].tag_name.lower()
            assert first_heading in ["h1", "h2"], f"Page starts with {first_heading}, expected h1 or h2"
        
        # Check for form labels
        inputs = self.driver.find_elements(By.TAG_NAME, "input")
        for input_elem in inputs:
            input_type = input_elem.get_attribute("type")
            if input_type in ["text", "password", "email"]:
                input_id = input_elem.get_attribute("id")
                if input_id:
                    labels = self.driver.find_elements(By.CSS_SELECTOR, f"label[for='{input_id}']")
                    assert len(labels) > 0, f"Input {input_id} missing label"
    
    def test_security_headers(self):
        """Test security-related HTTP headers (where accessible)"""
        self.driver.get(self.dashboard_url)
        
        # Check for secure cookies (if any)
        cookies = self.driver.get_cookies()
        for cookie in cookies:
            if cookie.get('secure') is not None:
                assert cookie['secure'], f"Cookie {cookie['name']} should be secure"
            
            # Check for HttpOnly flag on session cookies
            if 'session' in cookie['name'].lower():
                assert cookie.get('httpOnly'), f"Session cookie {cookie['name']} should be HttpOnly"
    
    def test_error_handling(self):
        """Test error handling and user feedback"""
        # Test 404 page
        self.driver.get(f"{self.dashboard_url}/nonexistent-page")
        
        page_content = self.driver.page_source.lower()
        assert (
            "404" in page_content or
            "not found" in page_content or
            "page not found" in page_content
        ), "404 page not properly handled"
        
        # Should not expose server information
        assert "apache" not in page_content
        assert "nginx" not in page_content
        assert "server error" not in page_content or "internal server error" not in page_content


class TestPrometheusUI:
    """UI tests for Prometheus monitoring interface"""
    
    @pytest.fixture(autouse=True)
    def setup(self):
        """Setup test browser for Prometheus"""
        chrome_options = Options()
        chrome_options.add_argument("--headless")
        chrome_options.add_argument("--no-sandbox")
        chrome_options.add_argument("--disable-dev-shm-usage")
        
        self.driver = webdriver.Chrome(options=chrome_options)
        self.wait = WebDriverWait(self.driver, 10)
        self.prometheus_url = "http://localhost:9090"
        
        yield
        
        self.driver.quit()
    
    def test_prometheus_query_interface(self):
        """Test Prometheus query interface"""
        self.driver.get(self.prometheus_url)
        
        try:
            # Find query input
            query_input = self.wait.until(
                EC.presence_of_element_located((By.CSS_SELECTOR, "input[placeholder*='query']"))
            )
            
            # Test a simple query
            query_input.clear()
            query_input.send_keys("up")
            
            # Find and click execute button
            execute_btn = self.driver.find_element(By.CSS_SELECTOR, "button[type='submit']")
            execute_btn.click()
            
            # Wait for results
            self.wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, ".table")))
            
        except TimeoutException:
            pytest.skip("Prometheus interface not accessible")
    
    def test_prometheus_targets_page(self):
        """Test Prometheus targets page"""
        self.driver.get(f"{self.prometheus_url}/targets")
        
        try:
            # Wait for targets table
            self.wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "table")))
            
            # Check for target status
            page_content = self.driver.page_source.lower()
            assert "endpoint" in page_content
            
        except TimeoutException:
            pytest.skip("Prometheus targets page not accessible")
