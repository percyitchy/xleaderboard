import React, { useState } from 'react';
import GlassCard from '../UI/GlassCard';
import BuyPopup from '../UI/BuyPopup';
import './SpikeList.css';

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

// Helper for Fire Rating
const getFireRating = (amount) => {
    if (amount >= 30000) return '🔥🔥🔥';
    if (amount >= 20000) return '🔥🔥';
    if (amount >= 10000) return '🔥';
    return '';
};

// Spike Row Component
const SpikeRow = ({ spike, occurrence, onBuyClick }) => {
    const side = spike.outcome || 'Yes';
    const price = spike.price || 0;
    const amount = spike.amount_usd || 0;
    const fires = getFireRating(amount);

    return (
        <GlassCard className="spike-row">
            <div className="spike-row-icon">⚡</div>
            <div className="spike-row-content">
                <div className="spike-row-header">
                    {fires && <span className="spike-fire">{fires}</span>}
                    <span className="spike-badge">x{occurrence}</span>
                </div>
                <h3 className="spike-row-title">{spike.question}</h3>
                <div className="spike-row-stats">
                    <span className="spike-stat">
                        <span className="spike-stat-icon">🎯</span>
                        <span>Side: <strong>{side}</strong></span>
                    </span>
                    <span className="spike-stat">
                        <span className="spike-stat-icon">💥</span>
                        <span>Spike: <strong>{formatUsd(amount)}</strong></span>
                    </span>
                    <span className="spike-stat">
                        <span className="spike-stat-icon">💰</span>
                        <span>Price: <strong>{price.toFixed(2)}</strong></span>
                    </span>
                </div>
            </div>
            <div className="spike-row-right">
                <span className="spike-row-time">{formatTimestamp(spike.timestamp)}</span>
                <button
                    className="spike-row-buy-btn"
                    onClick={() => onBuyClick(spike)}
                >
                    Buy {side} at {price.toFixed(2)}
                </button>
            </div>
        </GlassCard>
    );
};

// Main SpikeList Component
const SpikeList = ({ spikes = [] }) => {
    const [selectedSpike, setSelectedSpike] = useState(null);

    const enrichedSpikes = React.useMemo(() => {
        // Sort by timestamp ascending to calculate occurrences in order
        const sorted = [...spikes].sort((a, b) => a.timestamp - b.timestamp);
        const counts = {};
        const spikeMap = new Map(); // Map<spike, count>

        sorted.forEach(s => {
            const id = s.market_id;
            counts[id] = (counts[id] || 0) + 1;
            spikeMap.set(s, counts[id]);
        });

        // Return original list with occurrence data (preserving original sort order from props)
        return spikes.map(s => ({
            ...s,
            occurrence: spikeMap.get(s) || 1
        }));
    }, [spikes]);

    const handleBuyClick = (spike) => {
        setSelectedSpike(spike);
    };

    return (
        <div className="spike-list-container">
            <div className="spike-list">
                {enrichedSpikes.map((spike, idx) => (
                    <SpikeRow
                        key={spike.market_id || idx}
                        spike={spike}
                        occurrence={spike.occurrence}
                        onBuyClick={handleBuyClick}
                    />
                ))}
                {spikes.length === 0 && (
                    <div className="spike-list-empty">No volume spikes detected</div>
                )}
            </div>

            <BuyPopup
                isOpen={!!selectedSpike}
                onClose={() => setSelectedSpike(null)}
                tokenId={selectedSpike?.asset_id}
                initialPrice={selectedSpike?.price}
                side={selectedSpike?.outcome || 'Yes'}
                question={selectedSpike?.question}
            />
        </div>
    );
};

export default SpikeList;

