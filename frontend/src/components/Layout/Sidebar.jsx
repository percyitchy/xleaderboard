import React from 'react';
import { useWallet } from '../../context/WalletContext';
import './Sidebar.css';

const navItems = [
    { id: 'dashboard', label: 'Dashboard', icon: '📊' },
    { id: 'fetcher', label: 'Market Fetcher', icon: '🔍' },
    { id: 'spikes', label: 'Volume Spike', icon: '📈' },
    { id: 'wallets', label: "Smart's Tracker", icon: '👛' },
    { id: 'leaderboard', label: 'X Leaderboard', icon: '🏆' },
    { id: 'alerts', label: 'Telegram Alerts', icon: '🔔' },
    { id: 'docs', label: 'Docs', icon: '📄' },
];

const Sidebar = ({ activeTab = 'fetcher', onTabChange }) => {
    const {
        isConnected,
        truncatedAddress,
        truncatedProxyWallet,
        isConnecting,
        needsProxyWallet,
        connectWallet,
        disconnectWallet,
        error,
        // L2 Credentials
        isTradingEnabled,
        isDerivingCredentials,
        deriveApiCredentials
    } = useWallet();

    return (
        <aside className="sidebar">
            <nav className="sidebar-nav">
                {navItems.map(item => (
                    <button
                        key={item.id}
                        className={`sidebar-nav-item ${activeTab === item.id ? 'active' : ''}`}
                        onClick={() => {
                            if (item.id === 'alerts') {
                                window.open('https://t.me/polymarketeye', '_blank');
                            } else if (item.id === 'docs') {
                                window.open('https://polymarket-eye.gitbook.io/docs/', '_blank');
                            } else {
                                onTabChange?.(item.id);
                            }
                        }}
                    >
                        <span className="sidebar-nav-icon">{item.icon}</span>
                        <span className="sidebar-nav-label">{item.label}</span>
                    </button>
                ))}
            </nav>

            <div className="sidebar-wallet">
                {/* Twitter/X Button */}
                <a
                    href="https://x.com/PolymarketEye"
                    target="_blank"
                    rel="noopener noreferrer"
                    className="twitter-btn"
                >
                    <img src="/x-logo.png" alt="X" />
                </a>

                {isConnected ? (
                    <div className="wallet-connected">
                        {needsProxyWallet && (
                            <div className="wallet-warning">
                                <span>⚠️ Proxy wallet не найден</span>
                                <a
                                    href="https://polymarket.com?via=finance"
                                    target="_blank"
                                    rel="noopener noreferrer"
                                    className="wallet-warning-link"
                                >
                                    Создать на Polymarket →
                                </a>
                            </div>
                        )}



                        {/* Trading Status */}
                        {truncatedProxyWallet && !needsProxyWallet && (
                            isTradingEnabled ? (
                                <div className="trading-enabled">
                                    <span className="trading-icon">✅</span>
                                    <span>Trading Enabled</span>
                                </div>
                            ) : (
                                <button
                                    className="enable-trading-btn"
                                    onClick={deriveApiCredentials}
                                    disabled={isDerivingCredentials}
                                >
                                    {isDerivingCredentials ? '⏳ Signing...' : '🔓 Enable Trading'}
                                </button>
                            )
                        )}

                        <button className="wallet-disconnect-btn" onClick={disconnectWallet}>
                            Disconnect
                        </button>
                    </div>
                ) : (
                    <button
                        className="wallet-connect-btn"
                        onClick={connectWallet}
                        disabled={isConnecting}
                    >
                        {isConnecting ? 'Connecting...' : '🔗 Connect Wallet'}
                    </button>
                )}
                {error && <div className="wallet-error">{error}</div>}
            </div>
        </aside>
    );
};

export default Sidebar;
