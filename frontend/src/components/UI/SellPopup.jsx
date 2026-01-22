import React, { useState, useEffect, useRef } from 'react';
import { ethers } from 'ethers';
import { useWallet } from '../../context/WalletContext';
import { getApiUrl } from '../../config';
import './SellPopup.css';

const API_BASE_URL = getApiUrl();

const SellPopup = ({ isOpen, onClose, position, onSold }) => {
    const {
        address,
        proxyWallet,
        isConnected,
        truncatedProxyWallet,
        userCredentials,
        isTradingEnabled
    } = useWallet();

    // Order type: 'market' or 'limit'
    const [orderType, setOrderType] = useState('market');
    const [percentage, setPercentage] = useState(100);
    const [limitPrice, setLimitPrice] = useState('');
    const [loading, setLoading] = useState(false);
    const [signingStep, setSigningStep] = useState(null);
    const [error, setError] = useState(null);
    const [success, setSuccess] = useState(null);
    const [vwapData, setVwapData] = useState(null);
    const [vwapLoading, setVwapLoading] = useState(false);
    const debounceRef = useRef(null);

    // Calculate shares to sell based on percentage
    const totalShares = position?.shares || 0;
    const sharesToSell = Math.floor((totalShares * percentage) / 100);

    // Price depends on order type
    const marketPrice = vwapData?.vwap || position?.current_price || 0;
    const effectivePrice = orderType === 'limit' && limitPrice ? parseFloat(limitPrice) : marketPrice;
    const estimatedProceeds = sharesToSell * effectivePrice;

    // Reset state when popup opens/closes
    useEffect(() => {
        if (isOpen) {
            setOrderType('market');
            setPercentage(100);
            setLimitPrice('');
            setError(null);
            setSuccess(null);
            setVwapData(null);
        }
    }, [isOpen]);

    // Set limit price from best bid when switching to limit
    useEffect(() => {
        if (orderType === 'limit' && !limitPrice && vwapData?.best_price) {
            setLimitPrice(vwapData.best_price.toFixed(2));
        }
    }, [orderType, vwapData]);

    // Fetch VWAP when percentage changes (for market orders)
    useEffect(() => {
        if (!isOpen || !position?.token_id || sharesToSell <= 0) {
            setVwapData(null);
            return;
        }

        const estimatedValue = sharesToSell * (position?.current_price || 0);
        if (estimatedValue < 1) {
            setVwapData(null);
            return;
        }

        if (debounceRef.current) clearTimeout(debounceRef.current);
        debounceRef.current = setTimeout(() => {
            fetchVwap(estimatedValue);
        }, 300);

        return () => clearTimeout(debounceRef.current);
    }, [percentage, isOpen, position]);

    const fetchVwap = async (amountUsdc) => {
        setVwapLoading(true);
        try {
            const response = await fetch(
                `${API_BASE_URL}/api/trade/orderbook-depth?token_id=${position.token_id}&side=SELL&amount=${amountUsdc}`
            );
            if (response.ok) {
                const data = await response.json();
                setVwapData(data);
            }
        } catch (err) {
            console.error('Failed to fetch VWAP:', err);
        } finally {
            setVwapLoading(false);
        }
    };

    const handleSell = async () => {
        // Validation
        if (!isConnected || !proxyWallet) {
            setError('Wallet not connected');
            return;
        }
        if (!isTradingEnabled || !userCredentials) {
            setError('Trading not enabled. Enable it in the sidebar first.');
            return;
        }
        if (sharesToSell <= 0) {
            setError('Select a valid percentage');
            return;
        }
        if (estimatedProceeds < 1) {
            setError('Minimum sell is $1');
            return;
        }

        // Limit order validation
        if (orderType === 'limit') {
            const price = parseFloat(limitPrice);
            if (!price || price <= 0 || price > 1) {
                setError('Enter a valid price (0.01 - 1.00)');
                return;
            }
        }

        // Check fillability for market orders
        if (orderType === 'market' && vwapData && !vwapData.is_fillable) {
            setError(`Not enough liquidity. Only $${(estimatedProceeds - vwapData.remaining_usdc).toFixed(2)} available.`);
            return;
        }

        // Confirmation
        const orderTypeLabel = orderType === 'limit' ? 'LIMIT' : 'MARKET';
        const confirmed = window.confirm(
            `Confirm ${orderTypeLabel} sale:\n\n` +
            `• Selling ${sharesToSell} ${position.outcome} shares (${percentage}%)\n` +
            `• Price: $${effectivePrice.toFixed(4)}\n` +
            `• Estimated proceeds: $${estimatedProceeds.toFixed(2)} USDC\n` +
            `• From wallet: ${truncatedProxyWallet}` +
            (orderType === 'limit' ? '\n\n⏳ Limit order will wait on orderbook until filled.' : '') +
            `\n\nYou will be asked to sign in MetaMask.`
        );
        if (!confirmed) return;

        setLoading(true);
        setError(null);
        setSuccess(null);

        try {
            // Determine price
            setSigningStep('preparing');
            let orderPrice;

            if (orderType === 'limit') {
                orderPrice = parseFloat(limitPrice);
            } else {
                // Market order: use VWAP worst_price directly (no buffer for SELL)
                // For FOK orders, price must be <= bids in orderbook to fill
                if (vwapData?.worst_price) {
                    orderPrice = Math.max(vwapData.worst_price, 0.01);
                } else {
                    try {
                        const priceCheck = await fetch(`${API_BASE_URL}/api/trade/best-price?token_id=${position.token_id}&side=SELL`);
                        if (priceCheck.ok) {
                            const priceData = await priceCheck.json();
                            orderPrice = Math.max(priceData.price * 0.99, 0.01);
                        } else {
                            orderPrice = Math.max((position?.current_price || 0.5) * 0.99, 0.01);
                        }
                    } catch (e) {
                        orderPrice = Math.max((position?.current_price || 0.5) * 0.99, 0.01);
                    }
                }
            }

            // Step 1: Prepare order
            const apiOrderType = orderType === 'limit' ? 'GTC' : 'FOK';
            const prepareResponse = await fetch(`${API_BASE_URL}/api/trade/prepare-order`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    user_address: address,
                    proxy_address: proxyWallet,
                    token_id: position.token_id,
                    price: orderPrice,
                    size: sharesToSell,
                    side: 'SELL',
                    order_type: apiOrderType
                })
            });

            if (!prepareResponse.ok) {
                const errorData = await prepareResponse.json();
                throw new Error(errorData.detail || 'Failed to prepare order');
            }

            const orderData = await prepareResponse.json();

            // Step 2: Sign with MetaMask
            setSigningStep('signing');
            const provider = new ethers.BrowserProvider(window.ethereum);
            const signer = await provider.getSigner();

            const signature = await signer.signTypedData(
                orderData.domain,
                { Order: orderData.types.Order },
                orderData.message
            );

            // Step 3: Submit order with correct order_type
            setSigningStep('submitting');

            const submitResponse = await fetch(`${API_BASE_URL}/api/trade/submit-order`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    signed_order: { ...orderData, signature },
                    user_api_key: userCredentials.apiKey,
                    user_api_secret: userCredentials.apiSecret,
                    user_passphrase: userCredentials.passphrase,
                    order_type: apiOrderType
                })
            });

            if (!submitResponse.ok) {
                const errorData = await submitResponse.json();
                throw new Error(errorData.detail || 'Order submission failed');
            }

            const result = await submitResponse.json();
            const successMsg = orderType === 'limit'
                ? `Limit order placed! ${sharesToSell} shares @ $${orderPrice.toFixed(2)}`
                : `Sold ${sharesToSell} shares! Tx: ${result.result?.transactionsHashes?.[0]?.slice(0, 10) || 'Pending'}...`;
            setSuccess(successMsg);

            // Notify parent to refresh
            setTimeout(() => {
                onSold?.();
            }, 2000);

        } catch (err) {
            setError(err.message || 'Transaction failed');
        } finally {
            setLoading(false);
            setSigningStep(null);
        }
    };

    const getButtonText = () => {
        if (signingStep === 'preparing') return 'Preparing...';
        if (signingStep === 'signing') return 'Sign in MetaMask...';
        if (signingStep === 'submitting') return 'Submitting...';
        if (loading) return 'Processing...';
        const label = orderType === 'limit' ? 'Place Limit Order' : 'Sell';
        return `${label} $${estimatedProceeds.toFixed(2)}`;
    };

    if (!isOpen || !position) return null;

    return (
        <div className="sell-popup-overlay" onClick={onClose}>
            <div className="sell-popup" onClick={e => e.stopPropagation()}>
                <button className="sell-popup-close" onClick={onClose}>×</button>

                <h2 className="sell-popup-title">Sell {position.outcome}</h2>
                <p className="sell-popup-question">{position.question}</p>

                {/* Order Type Tabs */}
                <div className="sell-order-tabs">
                    <button
                        className={`sell-tab ${orderType === 'market' ? 'active' : ''}`}
                        onClick={() => setOrderType('market')}
                        disabled={loading}
                    >
                        Market
                    </button>
                    <button
                        className={`sell-tab ${orderType === 'limit' ? 'active' : ''}`}
                        onClick={() => setOrderType('limit')}
                        disabled={loading}
                    >
                        Limit
                    </button>
                </div>

                <div className="sell-popup-info">
                    <div className="sell-info-row">
                        <span>Your Position:</span>
                        <strong>{totalShares.toFixed(0)} shares</strong>
                    </div>
                    <div className="sell-info-row">
                        <span>Best Bid:</span>
                        <strong className="sell-price">${(vwapData?.best_price || position.current_price || 0).toFixed(4)}</strong>
                        {orderType === 'market' && vwapData?.vwap && vwapData.vwap !== vwapData.best_price && (
                            <span className="vwap-indicator"> → Avg: ${vwapData.vwap.toFixed(4)}</span>
                        )}
                        {vwapLoading && <span className="vwap-loading"> ⏳</span>}
                    </div>
                </div>

                {/* Limit Price Input (only for limit orders) */}
                {orderType === 'limit' && (
                    <div className="sell-limit-price">
                        <label>Your Sell Price</label>
                        <div className="limit-price-input-wrapper">
                            <span className="limit-price-symbol">$</span>
                            <input
                                type="number"
                                min="0.01"
                                max="1"
                                step="0.01"
                                value={limitPrice}
                                onChange={e => setLimitPrice(e.target.value)}
                                placeholder="0.00"
                                className="limit-price-input"
                                disabled={loading}
                            />
                        </div>
                        <p className="limit-price-hint">
                            Order will wait on orderbook until someone buys at this price
                        </p>
                    </div>
                )}

                <div className="sell-popup-percentage">
                    <label>Percentage to Sell</label>
                    <div className="percentage-buttons">
                        {[25, 50, 75, 100].map(p => (
                            <button
                                key={p}
                                className={`percentage-btn ${percentage === p ? 'active' : ''}`}
                                onClick={() => setPercentage(p)}
                                disabled={loading}
                            >
                                {p}%
                            </button>
                        ))}
                    </div>
                    <input
                        type="range"
                        min="1"
                        max="100"
                        value={percentage}
                        onChange={e => setPercentage(parseInt(e.target.value))}
                        className="percentage-slider"
                        disabled={loading}
                    />
                    <div className="percentage-value">{percentage}%</div>
                </div>

                <div className="sell-popup-summary">
                    <div className="summary-row">
                        <span>Shares to Sell:</span>
                        <strong>{sharesToSell}</strong>
                    </div>
                    <div className="summary-row">
                        <span>{orderType === 'limit' ? 'Price:' : 'Est. Price:'}</span>
                        <strong>${effectivePrice.toFixed(4)}</strong>
                    </div>
                    <div className="summary-row">
                        <span>Proceeds:</span>
                        <strong className="summary-proceeds">${estimatedProceeds.toFixed(2)} USDC</strong>
                    </div>
                </div>

                {orderType === 'market' && vwapData && !vwapData.is_fillable && (
                    <div className="sell-popup-warning">
                        ⚠️ Not enough liquidity for market order
                    </div>
                )}

                {orderType === 'limit' && limitPrice && parseFloat(limitPrice) > (vwapData?.best_price || position.current_price || 0) * 1.1 && (
                    <div className="sell-popup-warning">
                        ⚠️ Price is 10%+ above best bid - may take time to fill
                    </div>
                )}

                {error && <div className="sell-popup-error">{error}</div>}
                {success && <div className="sell-popup-success">{success}</div>}

                <div className="sell-popup-actions">
                    <button className="sell-popup-cancel" onClick={onClose} disabled={loading}>
                        Cancel
                    </button>
                    <button
                        className="sell-popup-confirm"
                        onClick={handleSell}
                        disabled={loading || sharesToSell <= 0 || estimatedProceeds < 1 || !isConnected || !isTradingEnabled}
                    >
                        {getButtonText()}
                    </button>
                </div>
            </div>
        </div>
    );
};

export default SellPopup;
