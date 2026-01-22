import React, { useState } from 'react';
import GlassCard from '../UI/GlassCard';
import BuyPopup from '../UI/BuyPopup';
import './SignalGrid.css';

const formatTimestamp = (ts) => {
    const date = new Date(ts * 1000);
    return date.toLocaleDateString('en-GB', {
        day: '2-digit',
        month: 'short',
        hour: '2-digit',
        minute: '2-digit',
    });
};

const formatUsd = (amount) => {
    if (typeof amount !== 'number') return '$0';
    return `$${amount.toLocaleString('en-US', { minimumFractionDigits: 0, maximumFractionDigits: 0 })}`;
};

// Signal Card Component
const SignalCard = ({ signal, onClick, onBuyClick }) => {
    const walletCount = signal.wallets?.length || 0;
    const spike = signal.usdc_size || 0;
    const side = signal.outcome || 'No';

    const handleBuyClick = (e) => {
        e.stopPropagation(); // Prevent card click
        onBuyClick?.(signal);
    };

    return (
        <GlassCard className="signal-card" onClick={() => onClick?.(signal)}>
            <div className="signal-card-header">
                <span className="signal-card-time">{formatTimestamp(signal.timestamp)}</span>
            </div>
            <h3 className="signal-card-title">{signal.question}</h3>
            <div className="signal-card-stats">
                <span className="signal-stat">
                    <span className="signal-stat-icon">🎯</span>
                    <span>Side: <strong>{side}</strong></span>
                </span>
                <span className="signal-stat">
                    <span className="signal-stat-icon">💥</span>
                    <span>Spike: <strong>{formatUsd(spike)}</strong></span>
                </span>
                <span className="signal-stat">
                    <span className="signal-stat-icon">👛</span>
                    <span><strong>{walletCount}</strong> wallets bought</span>
                </span>
            </div>
            <button className="signal-card-buy-btn" onClick={handleBuyClick}>
                Buy {side.toUpperCase()} at {signal.price?.toFixed(2) || '0.21'}
            </button>
        </GlassCard>
    );
};

// Category columns configuration with colors
const categories = [
    { id: 'Overall', label: 'Overall', bgColor: 'rgba(255, 7, 58, 0.25)', borderColor: '#FF073A' },
    { id: 'Politics', label: 'Politics', bgColor: 'rgba(4, 217, 255, 0.25)', borderColor: '#04D9FF' },
    { id: 'Crypto', label: 'Crypto', bgColor: 'rgba(255, 149, 0, 0.25)', borderColor: '#FF9500' },
    { id: 'Sports', label: 'Sports', bgColor: 'rgba(57, 255, 20, 0.25)', borderColor: '#39FF14' },
];

// Main SignalGrid Component
const SignalGrid = ({ signals = [], onSignalClick }) => {
    const [selectedBuySignal, setSelectedBuySignal] = useState(null);

    const handleBuyClick = (signal) => {
        setSelectedBuySignal(signal);
    };

    // Group signals by category
    const signalsByCategory = {};
    categories.forEach(cat => {
        signalsByCategory[cat.id] = signals.filter(s => s.category === cat.id);
    });

    return (
        <div className="signal-grid-container">
            {/* Category Headers Row */}
            <div className="signal-grid-headers">
                {categories.map(cat => (
                    <div
                        key={cat.id}
                        className="signal-header-pill"
                        style={{
                            backgroundColor: cat.bgColor,
                            borderColor: cat.borderColor,
                        }}
                    >
                        {cat.label}
                    </div>
                ))}
            </div>

            {/* Category Columns */}
            <div className="signal-grid-columns">
                {categories.map(cat => (
                    <div key={cat.id} className="signal-column">
                        <div className="signal-column-cards">
                            {signalsByCategory[cat.id]?.map((signal, idx) => (
                                <SignalCard
                                    key={signal.market_id || idx}
                                    signal={signal}
                                    onClick={onSignalClick}
                                    onBuyClick={handleBuyClick}
                                />
                            ))}
                            {signalsByCategory[cat.id]?.length === 0 && (
                                <div className="signal-column-empty">No signals</div>
                            )}
                        </div>
                    </div>
                ))}
            </div>

            <BuyPopup
                isOpen={!!selectedBuySignal}
                onClose={() => setSelectedBuySignal(null)}
                tokenId={selectedBuySignal?.asset_id}
                initialPrice={selectedBuySignal?.price}
                side={selectedBuySignal?.outcome || 'No'}
                question={selectedBuySignal?.question}
            />
        </div>
    );
};

export default SignalGrid;

