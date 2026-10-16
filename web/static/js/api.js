/**
 * API Client for Gateway Provisioning Station
 */
const API = {
  baseUrl: '',

  async request(endpoint, options = {}) {
    const defaultHeaders = {
      'Content-Type': 'application/json',
      'Accept': 'application/json'
    };

    const config = {
      ...options,
      headers: { ...defaultHeaders, ...options.headers }
    };

    try {
      const response = await fetch(`${this.baseUrl}${endpoint}`, config);
      const data = await response.json();
      if (!response.ok || data.success === false) {
        throw new Error(data.error || `HTTP error ${response.status}`);
      }
      return data;
    } catch (err) {
      console.warn(`[API Error] ${endpoint}:`, err.message);
      throw err;
    }
  },

  getGateways() {
    return this.request('/api/gateways');
  },

  getStatus(ip) {
    return this.request(`/api/status?ip=${encodeURIComponent(ip)}`);
  },

  provisionGateway(payload) {
    return this.request('/api/provision', {
      method: 'POST',
      body: JSON.stringify(payload)
    });
  }
};
