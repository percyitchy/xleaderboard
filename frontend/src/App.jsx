import React, { useState, useEffect } from 'react';
import Sidebar from './components/Layout/Sidebar';
import DynamicBackground from './components/Layout/DynamicBackground';
import Dashboard from './components/Dashboard/Dashboard';
import MarketGrid from './components/Fetcher/MarketGrid';
import SignalGrid from './components/SmartWallets/SignalGrid';
import SpikeList from './components/VolumeSpike/SpikeList';
import Leaderboard from './components/Leaderboard/Leaderboard';
import SlideOverPanel from './components/UI/SlideOverPanel';
import MarketDetailPanel from './components/Fetcher/MarketDetailPanel';
import SignalDetailPanel from './components/SmartWallets/SignalDetailPanel';
import { getApiUrl } from './config';
import './index.css';

const API_BASE_URL = getApiUrl();

function App() {
  const [activeTab, setActiveTab] = useState('fetcher');
  const [markets, setMarkets] = useState([]);
  const [signals, setSignals] = useState([]);
  const [spikes, setSpikes] = useState([]);
  const [loading, setLoading] = useState(true);
  const [filters, setFilters] = useState({ active: null });
  const [selectedMarket, setSelectedMarket] = useState(null);
  const [selectedSignal, setSelectedSignal] = useState(null);

  // Fetch fetcher markets
  useEffect(() => {
    const fetchMarkets = async () => {
      try {
        const response = await fetch(`${API_BASE_URL}/api/fetcher`);
        const data = await response.json();
        const marketList = Array.isArray(data) ? data : (data.data || []);
        setMarkets(marketList);
      } catch (error) {
        console.error('Failed to fetch markets:', error);
      } finally {
        setLoading(false);
      }
    };

    fetchMarkets();
  }, []);

  // Fetch wallet signals when tab changes
  useEffect(() => {
    if (activeTab !== 'wallets') return;

    const fetchSignals = async () => {
      try {
        const response = await fetch(`${API_BASE_URL}/api/wallets`);
        const data = await response.json();
        setSignals(Array.isArray(data) ? data : []);
      } catch (error) {
        console.error('Failed to fetch wallet signals:', error);
      }
    };

    fetchSignals();
  }, [activeTab]);

  // Fetch spikes when tab changes
  useEffect(() => {
    if (activeTab !== 'spikes') return;

    const fetchSpikes = async () => {
      try {
        const response = await fetch(`${API_BASE_URL}/api/spikes`);
        const data = await response.json();
        setSpikes(Array.isArray(data) ? data : []);
      } catch (error) {
        console.error('Failed to fetch spikes:', error);
      }
    };

    fetchSpikes();
  }, [activeTab]);

  const handleMarketClick = (market) => {
    setSelectedMarket(market);
  };

  const handleSignalClick = (signal) => {
    setSelectedSignal(signal);
  };

  const handleClosePanel = () => {
    setSelectedMarket(null);
    setSelectedSignal(null);
  };

  const handleFilterChange = (filterId) => {
    setFilters({ active: filterId });
  };

  return (
    <>
      <DynamicBackground />
      <div className="app-layout">
        <Sidebar activeTab={activeTab} onTabChange={setActiveTab} />
        <main className="app-main">
          {activeTab === 'dashboard' && (
            <Dashboard />
          )}
          {activeTab === 'fetcher' && (
            <MarketGrid
              markets={markets}
              onMarketClick={handleMarketClick}
              filters={filters}
              onFilterChange={handleFilterChange}
            />
          )}
          {activeTab === 'spikes' && (
            <SpikeList spikes={spikes} />
          )}
          {activeTab === 'wallets' && (
            <SignalGrid
              signals={signals}
              onSignalClick={handleSignalClick}
            />
          )}
          {activeTab === 'leaderboard' && (
            <Leaderboard />
          )}
          {activeTab !== 'dashboard' && activeTab !== 'fetcher' && activeTab !== 'wallets' && activeTab !== 'spikes' && activeTab !== 'leaderboard' && (
            <div style={{ padding: 40, color: 'white' }}>
              <h2>{activeTab.toUpperCase()} - Coming Soon</h2>
            </div>
          )}
        </main>
      </div>

      {/* Market Detail Slide-Over Panel (Fetcher) */}
      <SlideOverPanel isOpen={!!selectedMarket} onClose={handleClosePanel}>
        <MarketDetailPanel market={selectedMarket} onClose={handleClosePanel} />
      </SlideOverPanel>

      {/* Signal Detail Slide-Over Panel (SWT) */}
      <SlideOverPanel isOpen={!!selectedSignal} onClose={handleClosePanel}>
        <SignalDetailPanel signal={selectedSignal} />
      </SlideOverPanel>
    </>
  );
}

export default App;
