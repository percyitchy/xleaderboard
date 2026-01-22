import React, { useState } from 'react';
import BuyPopup from '../UI/BuyPopup';
import './SignalDetailPanel.css';

// Generate gradient colors for wallet icons
const walletColors = [
    'linear-gradient(135deg, #667eea 0%, #764ba2 100%)',
    'linear-gradient(135deg, #f093fb 0%, #f5576c 100%)',
    'linear-gradient(135deg, #4facfe 0%, #00f2fe 100%)',
    'linear-gradient(135deg, #43e97b 0%, #38f9d7 100%)',
    'linear-gradient(135deg, #fa709a 0%, #fee140 100%)',
    'linear-gradient(135deg, #a8edea 0%, #fed6e3 100%)',
];

const getWalletColor = (address) => {
    const hash = (address || '').split('').reduce((acc, char) => acc + char.charCodeAt(0), 0);
    return walletColors[hash % walletColors.length];
};

const truncateAddress = (address) => {
    if (!address || address.length <= 12) return address || '';
    return `${address.slice(0, 6)}...${address.slice(-4)}`;
};

const formatUsd = (amount) => {
    if (typeof amount !== 'number' || amount <= 0) return '—';
    return `$${amount.toLocaleString('en-US', { minimumFractionDigits: 0, maximumFractionDigits: 0 })}`;
};

const SignalDetailPanel = ({ signal }) => {
    const [showBuyPopup, setShowBuyPopup] = useState(false);

    if (!signal) return null;

    const wallets = signal.wallets || [];
    const spike = signal.usdc_size || 0;
    const walletCount = wallets.length;
    const price = signal.price || 0;
    const side = signal.outcome || 'No';

    const formatSpike = (num) => {
        if (num >= 1000000) return `$${(num / 1000000).toFixed(1)}M`;
        if (num >= 1000) return `$${Math.round(num / 1000).toLocaleString()}`;
        return `$${Math.round(num)}`;
    };

    return (
        <div className="signal-detail-panel">
            <h2 className="signal-detail-header">DIVE DEEPER INTO SMART HOLDERS</h2>

            <h3 className="signal-detail-title">
                <a
                    href={`https://polymarket.com/event/${signal.event_slug}/${signal.market_id}?via=finance`}
                    target="_blank"
                    rel="noopener noreferrer"
                    style={{ color: 'inherit', textDecoration: 'none' }}
                >
                    {signal.question}
                </a>
            </h3>

            <div className="signal-detail-stats">
                <div className="signal-detail-stat">
                    <span className="stat-icon">💥</span>
                    <span className="stat-value">Spike: {formatSpike(spike)}</span>
                </div>
                <div className="signal-detail-stat">
                    <span className="stat-icon">👛</span>
                    <span className="stat-value">{walletCount} wallets bought</span>
                </div>
            </div>

            <div className="wallet-table">
                <div className="wallet-table-header">
                    <span>Wallet</span>
                    <span>Winrate</span>
                    <span>Buy Price</span>
                    <span>Bet</span>
                </div>
                <div className="wallet-table-body">
                    {wallets.map((wallet, idx) => {
                        const address = wallet.address || wallet.wallet || `Wallet ${idx + 1}`;
                        const cleanAddress = address.replace(/^[^\x00-\x7F]+/, '');
                        const winrate = wallet.winrate || wallet.win_rate || 0;
                        const buyPrice = wallet.buy_price || wallet.price || signal.price || 0;
                        // Calculate Bet: shares * buy_price
                        const shares = wallet.shares || wallet.size || wallet.amount || 0;
                        const bet = shares > 0 && buyPrice > 0 ? shares * buyPrice : (wallet.bet || wallet.usdc || 0);

                        return (
                            <div key={idx} className="wallet-row">
                                <div className="wallet-col-address">
                                    <span className="wallet-icon" style={{ background: getWalletColor(address) }}></span>
                                    <span className="wallet-address">{truncateAddress(address)}</span>
                                </div>
                                <div className="wallet-col-winrate">
                                    {winrate > 0 ? `${winrate}%` : '—'}
                                </div>
                                <div className="wallet-col-price">
                                    {buyPrice > 0 ? buyPrice.toFixed(2) : '—'}
                                </div>
                                <div className="wallet-col-bet">
                                    {formatUsd(bet)}
                                </div>
                            </div>
                        );
                    })}
                </div>
            </div>

            <button
                className="signal-detail-buy-btn"
                onClick={() => setShowBuyPopup(true)}
            >
                Buy {side.toUpperCase()} at {price.toFixed(2)}
            </button>

            <BuyPopup
                isOpen={showBuyPopup}
                onClose={() => setShowBuyPopup(false)}
                tokenId={signal.asset_id}
                initialPrice={price}
                side={side}
                question={signal.question}
            />
        </div>
    );
};

export default SignalDetailPanel;

