import React, { useState } from 'react';
import FilterPill from '../UI/FilterPill';
import BuyPopup from '../UI/BuyPopup';
import './MarketDetailPanel.css';

// Generate random gradient colors for wallet icons
const walletColors = [
    'linear-gradient(135deg, #667eea 0%, #764ba2 100%)',
    'linear-gradient(135deg, #f093fb 0%, #f5576c 100%)',
    'linear-gradient(135deg, #4facfe 0%, #00f2fe 100%)',
    'linear-gradient(135deg, #43e97b 0%, #38f9d7 100%)',
    'linear-gradient(135deg, #fa709a 0%, #fee140 100%)',
    'linear-gradient(135deg, #a8edea 0%, #fed6e3 100%)',
];

const getWalletColor = (address) => {
    // Use address hash to consistently assign color
    const hash = address.split('').reduce((acc, char) => acc + char.charCodeAt(0), 0);
    return walletColors[hash % walletColors.length];
};

const truncateAddress = (address) => {
    // Remove emoji prefix if present
    const cleanAddress = address.replace(/^[^\x00-\x7F]+/, '');
    if (cleanAddress.length <= 12) return cleanAddress;
    return `${cleanAddress.slice(0, 6)}...${cleanAddress.slice(-4)}`;
};

const getWalletType = (address) => {
    if (address.startsWith('⚠️')) return 'new';
    if (address.startsWith('☎️')) return 'overbet';
    return 'fresh';
};

const formatUsd = (amount) => {
    if (typeof amount !== 'number') return '$0';
    return `$${amount.toLocaleString('en-US', { minimumFractionDigits: 0, maximumFractionDigits: 0 })}`;
};

const MarketDetailPanel = ({ market, onClose }) => {
    const [showBuyPopup, setShowBuyPopup] = useState(false);
    const [selectedSide, setSelectedSide] = useState('Yes');

    if (!market) return null;

    // Get holders for selected side
    const holdersYes = market.holders_yes || market.holders || {};
    const holdersNo = market.holders_no || {};
    const holders = selectedSide === 'Yes' ? holdersYes : holdersNo;
    const holderEntries = Object.entries(holders);

    // Count for both sides
    const yesCount = Object.keys(holdersYes).length;
    const noCount = Object.keys(holdersNo).length;

    const volume = market.total_volume || market.volume || 0;
    const priceYes = market.price_yes ?? market.price ?? 0;
    const priceNo = market.price_no ?? (1 - priceYes);
    const price = selectedSide === 'Yes' ? priceYes : priceNo;
    const assetID = selectedSide === 'Yes'
        ? (market.assetID_yes || market.assetID)
        : market.assetID_no;

    const formatVolume = (num) => {
        if (num >= 1000000) return `$${(num / 1000000).toFixed(1)}M`;
        if (num >= 1000) return `$${Math.round(num / 1000)}k`;
        return `$${Math.round(num)}`;
    };

    return (
        <div className="market-detail-panel">
            <h2 className="market-detail-header">DIVE DEEPER INTO SUS HOLDERS</h2>

            <h3 className="market-detail-title">
                <a
                    href={`https://polymarket.com/event/${market.event_slug}/${market.slug}?via=finance`}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="market-detail-link"
                    style={{ color: 'inherit', textDecoration: 'none' }}
                >
                    {market.question}
                </a>
            </h3>

            {/* YES/NO Toggle */}
            <div className="outcome-toggle">
                <button
                    className={`toggle-btn ${selectedSide === 'Yes' ? 'active yes' : ''}`}
                    onClick={() => setSelectedSide('Yes')}
                >
                    Yes ({yesCount})
                </button>
                <button
                    className={`toggle-btn ${selectedSide === 'No' ? 'active no' : ''}`}
                    onClick={() => setSelectedSide('No')}
                >
                    No ({noCount})
                </button>
            </div>

            <div className="market-detail-stats">
                <div className="market-detail-stat">
                    <span className="stat-icon">📈</span>
                    <span className="stat-value">{formatVolume(volume)} volume</span>
                </div>
                <div className="market-detail-stat">
                    <span className="stat-icon">🕵️</span>
                    <span className="stat-value">{yesCount}/{noCount} sus holders</span>
                </div>
                <div className="market-detail-stat">
                    <span className="stat-icon">🎯</span>
                    <span className="stat-value">Price: {price.toFixed(2)}</span>
                </div>
                {market.endDate && (
                    <div className="market-detail-stat">
                        <span className="stat-icon">⏰</span>
                        <span className="stat-value">End: {new Date(market.endDate).toLocaleDateString('en-GB', { day: 'numeric', month: 'short' })}</span>
                    </div>
                )}
            </div>

            <div className="wallet-table">
                <div className="wallet-table-header">
                    <span>Type</span>
                    <span>Wallet</span>
                    <span>Current Bet</span>
                </div>
                <div className="wallet-table-body">
                    {holderEntries.length > 0 ? holderEntries.map(([address, amount], idx) => {
                        const type = getWalletType(address);
                        const cleanAddress = address.replace(/^[^\x00-\x7F]+/, '');
                        const displayAddress = truncateAddress(address);
                        const gradient = getWalletColor(address);

                        return (
                            <div key={idx} className="wallet-row">
                                <div className="wallet-col-type">
                                    <FilterPill
                                        label={type === 'new' ? 'New' : type === 'overbet' ? 'Overbet' : 'Fresh'}
                                        variant={type === 'new' ? 'new' : type === 'overbet' ? 'hot' : 'fresh'}
                                        size="small"
                                        noHover
                                    />
                                </div>
                                <div className="wallet-col-address">
                                    <a
                                        href={`https://polymarket.com/profile/${cleanAddress}?via=finance`}
                                        target="_blank"
                                        rel="noopener noreferrer"
                                        className="wallet-address-link"
                                    >
                                        {displayAddress}
                                    </a>
                                </div>
                                <div className="wallet-col-bet">
                                    {formatUsd(amount)}
                                </div>
                            </div>
                        );
                    }) : (
                        <div className="wallet-row-empty">No {selectedSide} holders found</div>
                    )}
                </div>
            </div>

            <button
                className={`market-detail-buy-btn ${selectedSide.toLowerCase()}`}
                onClick={() => setShowBuyPopup(true)}
            >
                Buy {selectedSide.toUpperCase()} at {price.toFixed(2)}
            </button>

            <BuyPopup
                isOpen={showBuyPopup}
                onClose={() => setShowBuyPopup(false)}
                tokenId={assetID}
                initialPrice={price}
                side={selectedSide}
                question={market.question}
            />
        </div>
    );
};

export default MarketDetailPanel;

