class ProxyRotator:
    def __init__(self):
        self.raw_proxies = []
        self.working_proxies = []  
        self.sources = [
            "https://api.proxyscrape.com/v4/free-proxy-list/get?request=display_proxies&proxy_format=protocolipport&format=text&country=in&timeout=10000",
            "https://raw.githubusercontent.com/monosans/proxy-list/main/proxies/http.txt",
            "https://raw.githubusercontent.com/proxifly/free-proxy-list/main/proxies/countries/IN/data.txt"
        ]

    def refresh_proxies(self):
        """Fetch fresh raw Indian proxies."""
        new_proxies = []
        for url in self.sources:
            try:
                response = requests.get(url, timeout=10)
                if response.status_code == 200:
                    lines = response.text.splitlines()
                    new_proxies.extend(lines)
            except Exception as e:
                print(f"Error fetching proxies from {url}: {e}")
        
        self.raw_proxies = list(set([p.strip() for p in new_proxies if p.strip()]))
        random.shuffle(self.raw_proxies)
        print(f"Refreshed {len(self.raw_proxies)} raw proxies.")

    def _format_proxy(self, proxy_str):
        """Properly format the proxy string based on its protocol."""
        if proxy_str.startswith(('http://', 'https://', 'socks4://', 'socks5://')):
            return proxy_str
        return f"http://{proxy_str}"

    def _check_single_proxy(self, proxy_str, test_url):
        """Test a single proxy's availability and measure its latency."""
        proxy_url = self._format_proxy(proxy_str)
        proxy_dict = {"http": proxy_url, "https": proxy_url}
        start_time = time.time()
        
        try:
            # Relaxed to 3 seconds. Free proxies are too slow for 0.6s
            res = requests.get(test_url, proxies=proxy_dict, timeout=3.0)
            if res.status_code == 200:
                latency = time.time() - start_time
                return (latency, proxy_dict)
        except Exception:
            pass
        return None

    def populate_working_proxies(self, test_url="https://exams.dgma.gov.in", batch_size=50):
        """Perform parallel check on a batch of proxies and sort working ones by lowest latency."""
        if not self.raw_proxies:
            self.refresh_proxies()

        if not self.raw_proxies:
            return

        print(f"Testing proxy batch ({min(batch_size, len(self.raw_proxies))} candidates) for <= 3s latency...")
        candidates = [self.raw_proxies.pop(0) for _ in range(min(batch_size, len(self.raw_proxies)))]
        
        working_results = []
        with ThreadPoolExecutor(max_workers=15) as executor:
            futures = [executor.submit(self._check_single_proxy, p, test_url) for p in candidates]
            for future in futures:
                res = future.result()
                if res:
                    working_results.append(res)
        
        # Sort by latency (lowest response time first)
        working_results.sort(key=lambda x: x[0])
        
        # Extract just the proxy dicts into our working temp list
        self.working_proxies = [item[1] for item in working_results]
        print(f"✓ Found {len(self.working_proxies)} verified working proxies.")

    def get_proxy(self, test_url="https://exams.dgma.gov.in"):
        """Get the fastest working proxy available."""
        if not self.working_proxies:
            self.populate_working_proxies(test_url=test_url, batch_size=50)
        
        if self.working_proxies:
            return self.working_proxies.pop(0)
        
        # Direct raw fallback if no proxy passed the quick test
        if self.raw_proxies:
            raw = self.raw_proxies.pop(0)
            proxy_url = self._format_proxy(raw)
            return {"http": proxy_url, "https": proxy_url}
            
        return None
