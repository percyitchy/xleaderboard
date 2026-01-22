import React, { useState, useEffect, useRef } from 'react';
import { getApiUrl } from '../../config';
import './TraderHoverCard.css';

const API_BASE_URL = getApiUrl();

// In-memory cache
const statsCache = new Map();

// SessionStorage cache helper
const getCachedStats = (address) => {
    const cached = sessionStorage.getItem(`trader_stats_${address}`);
    if (cached) {
        try {
            const data = JSON.parse(cached);
            if (data.expiresAt > Date.now()) {
                return data.stats;
            }
        } catch (e) {
            // Invalid cache entry
        }
    }
    return null;
};

const setCachedStats = (address, stats) => {
    const expiresAt = Date.now() + 20 * 60 * 1000; // 20 minutes
    sessionStorage.setItem(
        `trader_stats_${address}`,
        JSON.stringify({ stats, expiresAt })
    );
};

const formatWinRate = (value) => {
    if (value === null || value === undefined) return null;
    return `${value.toFixed(0)}%`;
};

const formatPnl = (value) => {
    if (value === null || value === undefined) return null;
    const absValue = Math.abs(value);
    const prefix = value >= 0 ? '+' : '-';
    return `${prefix}$${absValue.toLocaleString('en-US', { maximumFractionDigits: 0 })}`;
};

const TraderHoverCard = ({ address, position, onClose }) => {
    const [stats, setStats] = useState(null);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState(false);
    const cardRef = useRef(null);
    const timeoutRef = useRef(null);

    useEffect(() => {
        if (!address) return;

        // Check in-memory cache first
        if (statsCache.has(address)) {
            const cached = statsCache.get(address);
            if (cached.expiresAt > Date.now()) {
                setStats(cached.stats);
                setLoading(false);
                return;
            } else {
                statsCache.delete(address);
            }
        }

        // Check sessionStorage
        const sessionCached = getCachedStats(address);
        if (sessionCached) {
            setStats(sessionCached);
            setLoading(false);
            // Also update in-memory cache
            statsCache.set(address, {
                stats: sessionCached,
                expiresAt: Date.now() + 20 * 60 * 1000
            });
            return;
        }

        // Fetch from API
        const fetchStats = async () => {
            try {
                const response = await fetch(
                    `${API_BASE_URL}/api/trader-stats?address=${encodeURIComponent(address)}`
                );
                
                if (!response.ok) {
                    throw new Error('Failed to fetch stats');
                }

                const data = await response.json();
                setStats(data);
                setError(false);

                // Cache in both places
                const expiresAt = Date.now() + 20 * 60 * 1000;
                statsCache.set(address, { stats: data, expiresAt });
                setCachedStats(address, data);
            } catch (err) {
                console.error('Error fetching trader stats:', err);
                setError(true);
                setStats({
                    winRate30d: null,
                    pnlAllTime: null,
                    favoriteCategory: null
                });
            } finally {
                setLoading(false);
            }
        };

        fetchStats();
    }, [address]);

    // Position the card
    useEffect(() => {
        if (cardRef.current && position) {
            const card = cardRef.current;
            const rect = position;
            
            // Position below the row, aligned to the left
            card.style.top = `${rect.bottom + 8}px`;
            card.style.left = `${rect.left}px`;
            
            // Adjust if card would go off screen
            const cardRect = card.getBoundingClientRect();
            if (cardRect.right > window.innerWidth) {
                card.style.left = `${window.innerWidth - cardRect.width - 16}px`;
            }
            if (cardRect.bottom > window.innerHeight) {
                card.style.top = `${rect.top - cardRect.height - 8}px`;
            }
        }
    }, [position, stats, loading]);

    return (
        <div 
            ref={cardRef} 
            className="trader-hover-card" 
            onClick={(e) => e.stopPropagation()}
            onMouseEnter={(e) => e.stopPropagation()}
            onMouseLeave={onClose}
        >
            {loading ? (
                <div className="trader-hover-card-loading">
                    <div className="trader-hover-card-skeleton">Loading...</div>
                </div>
            ) : error || !stats ? (
                <div className="trader-hover-card-error">No data</div>
            ) : (
                <div className="trader-hover-card-content">
                    {stats.winRate30d !== null && stats.winRate30d !== undefined ? (
                        <>
                            <div className="trader-hover-card-row">
                                <span className="trader-hover-card-label">30d win rate:</span>
                                <span className="trader-hover-card-value">{formatWinRate(stats.winRate30d)}</span>
                            </div>
                            {stats.winRate30d === 100 && (
                                <div className="trader-hover-card-note">
                                    *Based on closed markets only
                                </div>
                            )}
                        </>
                    ) : null}
                    {stats.pnlAllTime !== null && stats.pnlAllTime !== undefined ? (
                        <div className="trader-hover-card-row">
                            <span className="trader-hover-card-label">All-time PnL:</span>
                            <span className={`trader-hover-card-value ${stats.pnlAllTime >= 0 ? 'positive' : 'negative'}`}>
                                {formatPnl(stats.pnlAllTime)}
                            </span>
                        </div>
                    ) : null}
                    {stats.favoriteCategory ? (
                        <div className="trader-hover-card-row">
                            <span className="trader-hover-card-label">Top category:</span>
                            <span className="trader-hover-card-value">{stats.favoriteCategory}</span>
                        </div>
                    ) : null}
                    {stats.winRate30d === null && stats.pnlAllTime === null && !stats.favoriteCategory && (
                        <div className="trader-hover-card-error">No data</div>
                    )}
                </div>
            )}
        </div>
    );
};

export default TraderHoverCard;
