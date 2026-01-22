import React, { useState, useEffect } from 'react';
import { useWallet } from '../../context/WalletContext';
import GlassCard from '../UI/GlassCard';
import SellPopup from '../UI/SellPopup';
import { getApiUrl } from '../../config';
import './Dashboard.css';

const API_BASE_URL = getApiUrl();

const Dashboard = () => {
    const { address, proxyWallet, isConnected, truncatedAddress, truncatedProxyWallet, userCredentials, isTradingEnabled } = useWallet();
    const [positions, setPositions] = useState([]);
    const [openOrders, setOpenOrders] = useState([]);
    const [loading, setLoading] = useState(false);
    const [ordersLoading, setOrdersLoading] = useState(false);
    const [selectedPosition, setSelectedPosition] = useState(null);
    const [cancellingOrder, setCancellingOrder] = useState(null);

    // Fetch positions and orders when wallet is connected
    useEffect(() => {
        if (isConnected && proxyWallet) {
            fetchPositions();
            if (isTradingEnabled && userCredentials) {
                fetchOpenOrders();
            }
        } else {
            setPositions([]);
            setOpenOrders([]);
        }
    }, [isConnected, proxyWallet, isTradingEnabled]);

    const fetchPositions = async () => {
        if (!proxyWallet) return;

        setLoading(true);
        try {
            const response = await fetch(`${API_BASE_URL}/api/user/positions?address=${proxyWallet}`);
            if (response.ok) {
                const data = await response.json();
                setPositions(data);
            }
        } catch (err) {
            console.error('Failed to fetch positions:', err);
        } finally {
            setLoading(false);
        }
    };

    const fetchOpenOrders = async () => {
        if (!userCredentials || !address) return;

        setOrdersLoading(true);
        try {
            const response = await fetch(`${API_BASE_URL}/api/trade/open-orders`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    user_address: address,
                    user_api_key: userCredentials.apiKey,
                    user_api_secret: userCredentials.apiSecret,
                    user_passphrase: userCredentials.passphrase
                })
            });
            if (response.ok) {
                const data = await response.json();
                setOpenOrders(data.orders || []);
            }
        } catch (err) {
            console.error('Failed to fetch open orders:', err);
        } finally {
            setOrdersLoading(false);
        }
    };

    const handleCancelOrder = async (orderId) => {
        if (!userCredentials || !address) return;

        setCancellingOrder(orderId);
        try {
            const response = await fetch(`${API_BASE_URL}/api/trade/cancel-order`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    order_id: orderId,
                    user_address: address,
                    user_api_key: userCredentials.apiKey,
                    user_api_secret: userCredentials.apiSecret,
                    user_passphrase: userCredentials.passphrase
                })
            });

            if (response.ok) {
                // Refresh orders after cancel
                fetchOpenOrders();
            } else {
                const error = await response.json();
                console.error('Cancel failed:', error);
            }
        } catch (err) {
            console.error('Failed to cancel order:', err);
        } finally {
            setCancellingOrder(null);
        }
    };

    const handleSellClick = (position) => {
        setSelectedPosition(position);
    };

    const formatValue = (num) => {
        if (num >= 1000) return `$${(num / 1000).toFixed(1)}k`;
        return `$${num.toFixed(2)}`;
    };

    return (
        <div className="dashboard-container">
            {/* Header */}
            <div className="dashboard-header">
                <h1 className="dashboard-title">Dashboard</h1>
            </div>

            {/* User Info Card */}
            <div className="dashboard-user-card">
                <div className="user-card-avatar">
                    {isConnected ? '👛' : '🔒'}
                </div>
                <div className="user-card-info">
                    <div className="user-card-row">
                        <span className="user-card-icon">🪪</span>
                        <span className="user-card-label">Wallet:</span>
                        <span className="user-card-value">
                            {isConnected ? proxyWallet : 'Not Connected'}
                        </span>
                    </div>
                    <div className="user-card-row">
                        <span className="user-card-icon">💰</span>
                        <span className="user-card-label">Balance:</span>
                        <span className="user-card-value user-card-balance">--</span>
                    </div>
                    <div className="user-card-row">
                        <span className="user-card-icon">📈</span>
                        <span className="user-card-label">P&L:</span>
                        <span className="user-card-value user-card-pnl">--</span>
                    </div>
                </div>
            </div>

            {/* Positions Section */}
            <div className="dashboard-positions">
                <h2 className="positions-title">Positions</h2>

                {!isConnected ? (
                    <div className="positions-empty">
                        Connect your wallet to see positions
                    </div>
                ) : loading ? (
                    <div className="positions-loading">Loading positions...</div>
                ) : positions.length === 0 ? (
                    <div className="positions-empty">No active positions</div>
                ) : (
                    <div className="positions-grid">
                        {positions.map((pos, idx) => (
                            <GlassCard key={pos.token_id || idx} className="position-card">
                                <h3 className="position-question">{pos.question}</h3>
                                <div className="position-details">
                                    <div className="position-row">
                                        <span className="position-label">Side:</span>
                                        <span className={`position-side ${pos.outcome?.toLowerCase()}`}>
                                            {pos.outcome}
                                        </span>
                                    </div>
                                    <div className="position-row">
                                        <span className="position-label">Size:</span>
                                        <span className="position-value">
                                            {formatValue(pos.value_usd)} ({pos.shares.toFixed(0)} shares)
                                        </span>
                                    </div>
                                </div>
                                <button
                                    className="position-sell-btn"
                                    onClick={() => handleSellClick(pos)}
                                >
                                    SELL
                                </button>
                            </GlassCard>
                        ))}
                    </div>
                )}
            </div>

            {/* Open Orders Section - always show when trading enabled */}
            {isTradingEnabled && (
                <div className="dashboard-orders">
                    <h2 className="orders-title">Open Limit Orders</h2>
                    {ordersLoading ? (
                        <div className="orders-empty">Loading orders...</div>
                    ) : openOrders.length === 0 ? (
                        <div className="orders-empty">No open limit orders</div>
                    ) : (
                        <div className="orders-list">
                            {openOrders.map((order) => {
                                // Try to find market name from positions by matching asset_id
                                const matchedPosition = positions.find(p => p.token_id === order.asset_id);
                                const marketName = matchedPosition?.question || 'Unknown Market';
                                const truncatedName = marketName.length > 50 ? marketName.slice(0, 50) + '...' : marketName;

                                return (
                                    <div key={order.id} className="order-item">
                                        <div className="order-info">
                                            <span className="order-market">{truncatedName}</span>
                                            <div className="order-details">
                                                <span className={`order-side ${order.side?.toLowerCase()}`}>
                                                    {order.side}
                                                </span>
                                                <span className="order-size">
                                                    {order.size || order.original_size} @ ${parseFloat(order.price).toFixed(2)}
                                                </span>
                                            </div>
                                        </div>
                                        <button
                                            className="order-cancel-btn"
                                            onClick={() => handleCancelOrder(order.id)}
                                            disabled={cancellingOrder === order.id}
                                        >
                                            {cancellingOrder === order.id ? '...' : '✕'}
                                        </button>
                                    </div>
                                );
                            })}
                        </div>
                    )}
                </div>
            )}

            {/* Sell Popup */}
            <SellPopup
                isOpen={!!selectedPosition}
                onClose={() => setSelectedPosition(null)}
                position={selectedPosition}
                onSold={() => {
                    setSelectedPosition(null);
                    fetchPositions(); // Refresh positions after sell
                    fetchOpenOrders(); // Refresh orders too
                }}
            />
        </div>
    );
};

export default Dashboard;
