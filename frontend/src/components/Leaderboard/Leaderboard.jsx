import React, { useEffect, useMemo, useState, useRef } from 'react';
import GlassCard from '../UI/GlassCard';
import FilterPill from '../UI/FilterPill';
import TraderHoverCard from './TraderHoverCard';
import { getApiUrl } from '../../config';
import './Leaderboard.css';

const API_BASE_URL = getApiUrl();
const PAGE_SIZE = 100;

const PERIODS = [
    { id: 'DAY', label: '24H', variant: 'hot' },
    { id: 'WEEK', label: '7D', variant: 'whale' },
    { id: 'MONTH', label: '30D', variant: 'fresh' },
];

const formatUsd = (value) => {
    if (typeof value !== 'number' || Number.isNaN(value)) return '$0';
    return `$${value.toLocaleString('en-US', { maximumFractionDigits: 0 })}`;
};

const formatOpenPositions = (value) => {
    if (typeof value !== 'number' || Number.isNaN(value)) return '—';
    return value.toLocaleString('en-US');
};

const formatPnl = (value) => {
    if (typeof value !== 'number' || Number.isNaN(value)) return '—';
    const absValue = Math.abs(value);
    const prefix = value >= 0 ? '+' : '-';
    return `${prefix}${formatUsd(absValue)}`;
};

const shortWallet = (wallet) => {
    if (!wallet) return '';
    return `${wallet.slice(0, 6)}...${wallet.slice(-4)}`;
};

const LeaderboardRow = ({ entry }) => {
    const name = entry.name || entry.x_username || shortWallet(entry.proxy_wallet);
    const polymarketUrl = entry.proxy_wallet
        ? `https://polymarket.com/profile/${entry.proxy_wallet}`
        : null;
    const xUrl = entry.x_username ? `https://x.com/${entry.x_username}` : null;
    const pnlValue = typeof entry.pnl === 'number' ? entry.pnl : 0;
    
    const [showHoverCard, setShowHoverCard] = useState(false);
    const [hoverPosition, setHoverPosition] = useState(null);
    const hoverTimeoutRef = useRef(null);
    const rowRef = useRef(null);

    const handleMouseEnter = (e) => {
        // Clear any pending hide timeout
        if (hoverTimeoutRef.current) {
            clearTimeout(hoverTimeoutRef.current);
            hoverTimeoutRef.current = null;
        }

        // Set delay before showing hover card (200ms)
        hoverTimeoutRef.current = setTimeout(() => {
            if (rowRef.current) {
                const rect = rowRef.current.getBoundingClientRect();
                setHoverPosition(rect);
                setShowHoverCard(true);
            }
        }, 200);
    };

    const handleMouseLeave = () => {
        // Clear show timeout if mouse leaves before delay
        if (hoverTimeoutRef.current) {
            clearTimeout(hoverTimeoutRef.current);
            hoverTimeoutRef.current = null;
        }
        
        // Small delay before hiding (to allow moving to hover card)
        hoverTimeoutRef.current = setTimeout(() => {
            setShowHoverCard(false);
            setHoverPosition(null);
        }, 150);
    };

    useEffect(() => {
        return () => {
            if (hoverTimeoutRef.current) {
                clearTimeout(hoverTimeoutRef.current);
            }
        };
    }, []);

    return (
        <>
            <GlassCard 
                ref={rowRef}
                className="leaderboard-row leaderboard-row-hoverable"
                onMouseEnter={handleMouseEnter}
                onMouseLeave={handleMouseLeave}
            >
                <div className="leaderboard-cell leaderboard-rank">{entry.rank}</div>
                <div className="leaderboard-cell leaderboard-user">
                    <div className="leaderboard-avatar">
                        {entry.profile_image ? (
                            <img
                                src={entry.profile_image}
                                alt={name}
                                onError={(e) => {
                                    e.currentTarget.style.display = 'none';
                                }}
                            />
                        ) : (
                            <span>{name?.[0] || '?'}</span>
                        )}
                    </div>
                    <div className="leaderboard-user-meta">
                        <div className="leaderboard-user-name">
                            {name}
                            {entry.verified_badge && <span className="leaderboard-verified">✔︎</span>}
                        </div>
                        <div className="leaderboard-user-handle">
                            {entry.x_username ? `@${entry.x_username}` : shortWallet(entry.proxy_wallet)}
                        </div>
                    </div>
                </div>
                <div className={`leaderboard-cell leaderboard-pnl ${typeof pnlValue === 'number' && pnlValue >= 0 ? 'positive' : 'negative'}`}>
                    {formatPnl(pnlValue)}
                </div>
                <div className="leaderboard-cell leaderboard-open">
                    {formatOpenPositions(entry.open_positions)}
                </div>
                <div className="leaderboard-cell leaderboard-links">
                    {polymarketUrl && (
                        <a href={polymarketUrl} target="_blank" rel="noopener noreferrer" onClick={(e) => e.stopPropagation()}>
                            Profile
                        </a>
                    )}
                    {xUrl && (
                        <a href={xUrl} target="_blank" rel="noopener noreferrer" onClick={(e) => e.stopPropagation()}>
                            X
                        </a>
                    )}
                </div>
            </GlassCard>
            {showHoverCard && entry.proxy_wallet && (
                <TraderHoverCard
                    address={entry.proxy_wallet}
                    position={hoverPosition}
                    onClose={() => {
                        setShowHoverCard(false);
                        setHoverPosition(null);
                    }}
                />
            )}
        </>
    );
};

const Leaderboard = () => {
    const [period, setPeriod] = useState('DAY');
    const [page, setPage] = useState(1);
    const [entries, setEntries] = useState([]);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState(null);
    const [hasMore, setHasMore] = useState(false);
    const [asOf, setAsOf] = useState(null);
    const [openPositionsEnabled, setOpenPositionsEnabled] = useState(false);

    const offset = useMemo(() => (page - 1) * PAGE_SIZE, [page]);

    useEffect(() => {
        const controller = new AbortController();

        const fetchLeaderboard = async () => {
            setLoading(true);
            setError(null);
            try {
                const response = await fetch(
                    `${API_BASE_URL}/api/leaderboard?period=${period}&limit=${PAGE_SIZE}&offset=${offset}&only_twitter=true&pnl_source=user_pnl&include_open_positions=${openPositionsEnabled}`,
                    { signal: controller.signal }
                );
                if (!response.ok) {
                    throw new Error(`Failed to fetch leaderboard: ${response.status}`);
                }
                const payload = await response.json();
                const items = Array.isArray(payload) ? payload : payload.items || [];
                setEntries(items);
                setHasMore(Boolean(payload.meta?.has_more));
                setAsOf(payload.meta?.as_of || null);
            } catch (err) {
                if (err.name !== 'AbortError') {
                    setError(err.message || 'Failed to load leaderboard');
                }
            } finally {
                setLoading(false);
            }
        };

        fetchLeaderboard();

        return () => controller.abort();
    }, [period, offset, openPositionsEnabled]);

    const handlePeriodChange = (nextPeriod) => {
        setPeriod(nextPeriod);
        setPage(1);
    };

    return (
        <div className="leaderboard-container">
            <div className="leaderboard-header">
                <div>
                    <h2>Leaderboard — X-Linked Accounts</h2>
                    <p>Top Polymarket traders with linked X accounts, ranked by PnL.</p>
                    <p className="leaderboard-note">
                        Open Positions show unresolved positions priced between $0 and $1.
                    </p>
                </div>
                <div className="leaderboard-filters">
                    {PERIODS.map((item) => (
                        <FilterPill
                            key={item.id}
                            label={item.label}
                            variant={item.variant}
                            active={period === item.id}
                            onClick={() => handlePeriodChange(item.id)}
                        />
                    ))}
                    <FilterPill
                        label={openPositionsEnabled ? 'Open Positions: ON' : 'Open Positions: OFF'}
                        variant={openPositionsEnabled ? 'gain' : 'gray'}
                        active={openPositionsEnabled}
                        onClick={() => setOpenPositionsEnabled((prev) => !prev)}
                    />
                </div>
            </div>

            <div className="leaderboard-table">
                <div className="leaderboard-row leaderboard-header-row">
                    <div className="leaderboard-cell leaderboard-rank">#</div>
                    <div className="leaderboard-cell leaderboard-user">Account</div>
                    <div className="leaderboard-cell leaderboard-pnl">PnL</div>
                    <div className="leaderboard-cell leaderboard-open">Open Positions</div>
                    <div className="leaderboard-cell leaderboard-links">Links</div>
                </div>

                {loading && <div className="leaderboard-state">Loading leaderboard...</div>}
                {error && !loading && <div className="leaderboard-state error">{error}</div>}
                {!loading && !error && entries.length === 0 && (
                    <div className="leaderboard-state">No X-linked accounts found for this period.</div>
                )}
                {!loading && !error && entries.map((entry) => (
                    <LeaderboardRow key={`${entry.proxy_wallet}-${entry.rank}`} entry={entry} />
                ))}
            </div>

            <div className="leaderboard-footer">
                <div className="leaderboard-pagination">
                    <button onClick={() => setPage((p) => Math.max(1, p - 1))} disabled={page === 1}>
                        Prev
                    </button>
                    <span>Page {page}</span>
                    <button onClick={() => setPage((p) => p + 1)} disabled={!hasMore}>
                        Next
                    </button>
                </div>
                {asOf && (
                    <div className="leaderboard-asof">
                        Updated {new Date(asOf).toLocaleTimeString()}
                    </div>
                )}
            </div>
        </div>
    );
};

export default Leaderboard;
