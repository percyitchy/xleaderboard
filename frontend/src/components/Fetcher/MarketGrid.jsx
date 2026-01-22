import React, { useState, useMemo } from 'react';
import GlassCard from '../UI/GlassCard';
import FilterPill from '../UI/FilterPill';
import BuyPopup from '../UI/BuyPopup';
import logo from '../../assets/logo.png';
import './MarketGrid.css';

const formatVolume = (num) => {
    if (num >= 1000000) return `$${(num / 1000000).toFixed(1)}M`;
    if (num >= 1000) return `$${Math.round(num / 1000)}k`;
    return `$${Math.round(num)}`;
};

// Parse holders object to get counts by type
const parseHolders = (holders) => {
    if (!holders || typeof holders !== 'object') {
        return { susCount: 0, newCount: 0, freshCount: 0, overbetCount: 0 };
    }

    // Handle both dict and array formats
    const keys = Array.isArray(holders) ? holders.map(h => h.address || '') : Object.keys(holders);
    const susCount = keys.length;
    const newCount = keys.filter(k => k.startsWith('⚠️')).length;
    const overbetCount = keys.filter(k => k.startsWith('☎️')).length;
    // Fresh = no emoji prefix (not ⚠️ and not ☎️)
    const freshCount = keys.filter(k => !k.startsWith('⚠️') && !k.startsWith('☎️')).length;

    return {
        susCount,
        newCount,
        freshCount,
        overbetCount,
    };
};

// Fire emoji based on sus count
const getFireEmoji = (count) => {
    if (count < 10) return '';
    if (count < 20) return ' 🔥';
    if (count < 30) return ' 🔥🔥';
    return ' 🔥🔥🔥';
};

// Get outcome text from market data (first outcome from outcomes array)
const getOutcome = (market) => market?.outcome || 'Yes';

const MarketCard = ({ market, onClick, onBuyClick }) => {
    // Parse YES and NO holders separately
    const yesStats = parseHolders(market.holders_yes || market.holders);
    const noStats = parseHolders(market.holders_no);
    const totalSusCount = yesStats.susCount + noStats.susCount;

    const volume = market.total_volume || market.volume || 0;
    const fireEmoji = getFireEmoji(totalSusCount);

    // Separate YES/NO 24h gains - show only if at least one > 0
    const susGainYes = market.sus_gain_24h_yes ?? 0;
    const susGainNo = market.sus_gain_24h_no ?? 0;
    const hasGrowth = susGainYes > 0 || susGainNo > 0;

    const handleBuyYesClick = (e) => {
        e.stopPropagation();
        onBuyClick?.(market, 'Yes');
    };

    const handleBuyNoClick = (e) => {
        e.stopPropagation();
        onBuyClick?.(market, 'No');
    };

    return (
        <GlassCard className="market-card" onClick={() => onClick?.(market)}>
            <h3 className="market-card-title">{market.question}</h3>
            <div className="market-card-stats">
                <span className="market-stat">
                    <span className="market-stat-icon">📈</span>
                    <span className="market-stat-value">{formatVolume(volume)} volume</span>
                </span>
                <span className="market-stat">
                    <span className="market-stat-icon">🕵️</span>
                    <span className="market-stat-value"><strong>{yesStats.susCount} Yes / {noStats.susCount} No</strong> sus holders{fireEmoji}</span>
                    {hasGrowth && <span className="sus-gain">24h growth: {susGainYes}/{susGainNo}</span>}
                </span>
                <span className="market-stat">
                    <span className="market-stat-icon">🔮</span>
                    <span className="market-stat-value">Possible Outcome: {yesStats.susCount >= noStats.susCount ? 'Yes' : 'No'}</span>
                </span>
            </div>
            <div className="market-card-footer">
                <div className="market-card-tags">
                    {(yesStats.newCount + noStats.newCount) > 0 && (
                        <FilterPill label="New" count={yesStats.newCount + noStats.newCount} variant="new" size="small" noHover />
                    )}
                    {(yesStats.freshCount + noStats.freshCount) > 0 && (
                        <FilterPill label="Fresh" count={yesStats.freshCount + noStats.freshCount} variant="fresh" size="small" noHover />
                    )}
                    {(yesStats.overbetCount + noStats.overbetCount) > 0 && (
                        <FilterPill label="Overbet" count={yesStats.overbetCount + noStats.overbetCount} variant="hot" size="small" noHover />
                    )}
                </div>
                <button className="market-card-see-all" onClick={(e) => { e.stopPropagation(); onClick?.(market); }}>See all</button>
            </div>
            <div className="market-card-buy-buttons">
                <button className="market-card-buy-btn yes" onClick={handleBuyYesClick}>
                    BUY YES {(market.price_yes ?? market.price)?.toFixed(2)}
                </button>
                <button className="market-card-buy-btn no" onClick={handleBuyNoClick}>
                    BUY NO {(market.price_no ?? (1 - (market.price_yes ?? market.price ?? 0)))?.toFixed(2)}
                </button>
            </div>
        </GlassCard>
    );
};

const Header = () => (
    <div className="header">
        <div className="header-logo">
            <img src={logo} alt="Logo" className="header-logo-img" />
            <span className="header-logo-text">Polymarket Eye</span>
        </div>
    </div>
);

const MarketGrid = ({ markets = [], onMarketClick, filters, onFilterChange }) => {
    const [searchQuery, setSearchQuery] = useState('');
    const [isSearchFocused, setIsSearchFocused] = useState(false);
    const [selectedBuyMarket, setSelectedBuyMarket] = useState(null);
    const [selectedBuySide, setSelectedBuySide] = useState('Yes');

    const handleBuyClick = (market, side) => {
        setSelectedBuyMarket(market);
        setSelectedBuySide(side);
    };

    // Sort and filter markets based on active filter and search query
    const processedMarkets = useMemo(() => {
        let result = [...markets];

        // Apply search filter
        if (searchQuery.trim()) {
            const query = searchQuery.toLowerCase();
            result = result.filter(m => m.question?.toLowerCase().includes(query));
        }

        // Apply sorting based on active filter
        const activeFilter = filters?.active;

        if (activeFilter === 'hot') {
            // Hot & Sus: sort by combined sus count descending
            result.sort((a, b) => {
                const yesA = parseHolders(a.holders_yes || a.holders).susCount;
                const noA = parseHolders(a.holders_no).susCount;
                const yesB = parseHolders(b.holders_yes || b.holders).susCount;
                const noB = parseHolders(b.holders_no).susCount;
                return (yesB + noB) - (yesA + noA);
            });
        } else if (activeFilter === 'whale') {
            // Whale Watch: sort by volume descending
            result.sort((a, b) => {
                const volA = a.total_volume || a.volume || 0;
                const volB = b.total_volume || b.volume || 0;
                return volB - volA;
            });
        } else if (activeFilter === 'new') {
            // New Markets: sort by startDate descending (newest first)
            result.sort((a, b) => {
                const dateA = new Date(a.startDate || 0).getTime();
                const dateB = new Date(b.startDate || 0).getTime();
                return dateB - dateA;
            });
        } else if (activeFilter === 'gain') {
            // Gain Traction: sort by sus_gain_24h descending
            result.sort((a, b) => {
                const gainA = a.sus_gain_24h || 0;
                const gainB = b.sus_gain_24h || 0;
                return gainB - gainA;
            });
        } else if (activeFilter === 'ending') {
            // Ending Soon: sort by endDate ascending (soonest first)
            result.sort((a, b) => {
                const dateA = new Date(a.endDate || '2099-12-31').getTime();
                const dateB = new Date(b.endDate || '2099-12-31').getTime();
                return dateA - dateB;
            });
        }

        return result;
    }, [markets, filters?.active, searchQuery]);

    const handleFilterClick = (filterId) => {
        // Toggle filter: if already active, deselect; otherwise select
        if (filters?.active === filterId) {
            onFilterChange?.(null);
        } else {
            onFilterChange?.(filterId);
        }
    };

    return (
        <div className="market-grid-container">
            <Header />
            <div className="market-grid-filters">
                {/* Left side filters */}
                <FilterPill
                    label="Ending Soon"
                    icon="⏰"
                    variant="ending"
                    active={filters?.active === 'ending'}
                    onClick={() => handleFilterClick('ending')}
                />
                <FilterPill
                    label="Whale Watch"
                    icon="🐳"
                    variant="whale"
                    active={filters?.active === 'whale'}
                    onClick={() => handleFilterClick('whale')}
                />
                <FilterPill
                    label="Hot & Sus"
                    icon="🔥"
                    variant="hot"
                    active={filters?.active === 'hot'}
                    onClick={() => handleFilterClick('hot')}
                />

                {/* Search box in center */}
                <div className={`search-box ${isSearchFocused ? 'focused' : ''}`}>
                    <span className="search-icon">🔍</span>
                    <input
                        type="text"
                        className="search-input"
                        placeholder="Search"
                        value={searchQuery}
                        onChange={(e) => setSearchQuery(e.target.value)}
                        onFocus={() => setIsSearchFocused(true)}
                        onBlur={() => setIsSearchFocused(false)}
                    />
                </div>

                {/* Right side filters */}
                <FilterPill
                    label="Gain Traction"
                    icon="📈"
                    variant="gain"
                    active={filters?.active === 'gain'}
                    onClick={() => handleFilterClick('gain')}
                />
                <FilterPill
                    label="New Markets"
                    icon="🆕"
                    variant="new"
                    active={filters?.active === 'new'}
                    onClick={() => handleFilterClick('new')}
                />
            </div>
            <div className="market-grid">
                {processedMarkets.map((market, idx) => (
                    <MarketCard
                        key={market.id || market.assetID || idx}
                        market={market}
                        onClick={onMarketClick}
                        onBuyClick={handleBuyClick}
                    />
                ))}
            </div>

            <BuyPopup
                isOpen={!!selectedBuyMarket}
                onClose={() => setSelectedBuyMarket(null)}
                tokenId={selectedBuySide === 'Yes'
                    ? (selectedBuyMarket?.assetID_yes || selectedBuyMarket?.assetID)
                    : selectedBuyMarket?.assetID_no}
                initialPrice={selectedBuySide === 'Yes'
                    ? (selectedBuyMarket?.price_yes ?? selectedBuyMarket?.price)
                    : selectedBuyMarket?.price_no}
                side={selectedBuySide}
                question={selectedBuyMarket?.question}
            />
        </div>
    );
};

export default MarketGrid;
