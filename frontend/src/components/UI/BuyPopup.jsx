import React, { useState, useEffect, useRef } from 'react';
import { ethers } from 'ethers';
import { useWallet } from '../../context/WalletContext';
import './BuyPopup.css';

const BuyPopup = ({
    isOpen,
    onClose,
    tokenId,
    initialPrice,
    side,
    question
}) => {
    const {
        address,
        proxyWallet,
        isConnected,
        truncatedProxyWallet,
        // L2 Credentials
        userCredentials,
        isTradingEnabled
    } = useWallet();

    const [amount, setAmount] = useState('');
    const [price, setPrice] = useState(initialPrice || 0);
    const [loading, setLoading] = useState(false);
    const [signingStep, setSigningStep] = useState(null);
    const [error, setError] = useState(null);
    const [success, setSuccess] = useState(null);

    // VWAP state for accurate pricing on large orders
    const [vwapData, setVwapData] = useState(null);
    const [vwapLoading, setVwapLoading] = useState(false);
    const debounceRef = useRef(null);

    // Calculate cost using VWAP if available, else best price
    const shares = amount ? parseFloat(amount) : 0;
    const effectivePrice = (vwapData?.vwap && shares > 0) ? vwapData.vwap : price;
    const cost = shares * effectivePrice;

    // Fetch best ask price when popup opens
    useEffect(() => {
        if (isOpen && tokenId) {
            console.log('BuyPopup opened:', { tokenId, side, question, initialPrice });
            fetchBestPrice();
            setVwapData(null);
        }
    }, [isOpen, tokenId]);

    // Debounced VWAP fetch when amount changes
    useEffect(() => {
        if (!isOpen || !tokenId || !amount || parseFloat(amount) <= 0) {
            setVwapData(null);
            return;
        }

        const amountValue = parseFloat(amount) * price; // Approximate USD amount
        if (amountValue < 1) {
            setVwapData(null);
            return;
        }

        // Debounce 300ms
        if (debounceRef.current) clearTimeout(debounceRef.current);
        debounceRef.current = setTimeout(() => {
            fetchVwap(amountValue);
        }, 300);

        return () => clearTimeout(debounceRef.current);
    }, [amount, price, isOpen, tokenId]);

    const fetchBestPrice = async () => {
        try {
            const response = await fetch(`/api/trade/best-price?token_id=${tokenId}&side=BUY`);
            if (response.ok) {
                const data = await response.json();
                setPrice(data.price || initialPrice);
            } else {
                const fallback = await fetch(`/api/trade/price?token_id=${tokenId}`);
                if (fallback.ok) {
                    const data = await fallback.json();
                    setPrice(data.ask || initialPrice);
                }
            }
        } catch (err) {
            console.error('Failed to fetch price:', err);
        }
    };

    const fetchVwap = async (amountUsdc) => {
        setVwapLoading(true);
        try {
            const response = await fetch(
                `/api/trade/orderbook-depth?token_id=${tokenId}&side=BUY&amount=${amountUsdc}`
            );
            if (response.ok) {
                const data = await response.json();
                setVwapData(data);
                console.log('VWAP data:', data);
            }
        } catch (err) {
            console.error('Failed to fetch VWAP:', err);
        } finally {
            setVwapLoading(false);
        }
    };

    const handleBuy = async () => {
        // Validation
        if (!isConnected) {
            setError('Please connect your wallet first');
            return;
        }
        if (!proxyWallet) {
            setError('Polymarket proxy wallet not found. Please connect to Polymarket first.');
            return;
        }
        if (!isTradingEnabled || !userCredentials) {
            setError('Trading not enabled. Please click "Enable Trading" in the sidebar first.');
            return;
        }
        if (!shares || shares <= 0) {
            setError('Enter a valid amount');
            return;
        }
        if (cost < 1) {
            setError('Minimum order is $1');
            return;
        }


        // Check if fillable from VWAP data
        if (vwapData && !vwapData.is_fillable) {
            setError(`Not enough liquidity. Only $${(cost - vwapData.remaining_usdc).toFixed(2)} available.`);
            return;
        }

        // Use VWAP data for confirmation
        const displayPrice = vwapData?.vwap || effectivePrice;
        const displayShares = vwapData?.total_shares || shares;

        // Confirmation dialog with VWAP info
        const confirmed = window.confirm(
            `Confirm purchase:\n\n` +
            `• ~${displayShares.toFixed(2)} ${side} shares\n` +
            `• Avg price: $${displayPrice.toFixed(4)}\n` +
            `• Total cost: $${cost.toFixed(2)} USDC\n` +
            `• From wallet: ${truncatedProxyWallet}` +
            (vwapData?.levels_used > 1 ? `\n• Fills ${vwapData.levels_used} price levels` : '') +
            `\n\nYou will be asked to sign in MetaMask.`
        );
        if (!confirmed) return;

        setLoading(true);
        setError(null);
        setSuccess(null);

        // Auto-retry logic for "invalid signature" errors
        const MAX_RETRIES = 2;
        let lastError = null;

        try {
            for (let attempt = 0; attempt <= MAX_RETRIES; attempt++) {
                try {
                    if (attempt > 0) {
                        console.log(`Retry attempt ${attempt}/${MAX_RETRIES} - regenerating order...`);
                        setSigningStep('preparing');
                    }

                    // Use worst_price from VWAP if available, otherwise add slippage to best_ask
                    if (attempt === 0) setSigningStep('preparing');
                    let orderPrice;

                    if (vwapData?.worst_price) {
                        // Use worst_price directly (no buffer) for reliable FOK filling
                        orderPrice = Math.min(vwapData.worst_price, 0.99);
                        console.log(`Using VWAP worst_price: $${vwapData.worst_price} → order: $${orderPrice.toFixed(4)}`);
                    } else {
                        try {
                            const priceCheck = await fetch(`/api/trade/best-price?token_id=${tokenId}&side=BUY`);
                            if (priceCheck.ok) {
                                const priceData = await priceCheck.json();
                                orderPrice = Math.min(priceData.price * 1.01, 0.99);
                            } else {
                                orderPrice = Math.min(price * 1.01, 0.99);
                            }
                        } catch (e) {
                            orderPrice = Math.min(price * 1.01, 0.99);
                        }
                    }

                    // Step 1: Prepare order (fresh salt on each attempt)
                    const prepareResponse = await fetch('/api/trade/prepare-order', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({
                            user_address: address,
                            proxy_address: proxyWallet,
                            token_id: tokenId,
                            price: orderPrice,
                            size: shares,
                            side: 'BUY'
                        })
                    });

                    if (!prepareResponse.ok) {
                        const errorData = await prepareResponse.json();
                        throw new Error(errorData.detail || 'Failed to prepare order');
                    }

                    const orderData = await prepareResponse.json();
                    console.log('Order prepared:', orderData);

                    // Step 2: Sign with MetaMask
                    setSigningStep('signing');

                    const provider = new ethers.BrowserProvider(window.ethereum);
                    const signer = await provider.getSigner();

                    const domain = orderData.domain;
                    const types = { ...orderData.types };

                    // Convert uint256 fields to BigInt for ethers.js EIP-712 signing
                    // Ethers v6 requires native BigInt for uint256 types, not strings
                    const message = {
                        ...orderData.message,
                        salt: BigInt(orderData.message.salt),
                        tokenId: BigInt(orderData.message.tokenId),
                        makerAmount: BigInt(orderData.message.makerAmount),
                        takerAmount: BigInt(orderData.message.takerAmount),
                        expiration: BigInt(orderData.message.expiration),
                        nonce: BigInt(orderData.message.nonce),
                        feeRateBps: BigInt(orderData.message.feeRateBps),
                        side: parseInt(orderData.message.side, 10),
                        signatureType: parseInt(orderData.message.signatureType, 10)
                    };

                    delete types.EIP712Domain;

                    const signature = await signer.signTypedData(domain, types, message);
                    console.log('Order signed');

                    // Step 3: Submit order with user credentials
                    setSigningStep('submitting');
                    const submitResponse = await fetch('/api/trade/submit-order', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({
                            signed_order: {
                                ...orderData,
                                signature: signature
                            },
                            user_api_key: userCredentials.apiKey,
                            user_api_secret: userCredentials.apiSecret,
                            user_passphrase: userCredentials.passphrase
                        })
                    });

                    if (!submitResponse.ok) {
                        const errorData = await submitResponse.json();
                        const errorMsg = errorData.detail || 'Failed to submit order';

                        // Check if retryable "invalid signature" error
                        if (errorMsg.includes('invalid signature') && attempt < MAX_RETRIES) {
                            console.warn(`Invalid signature error, will retry... (${attempt + 1}/${MAX_RETRIES})`);
                            lastError = new Error(errorMsg);
                            continue; // Retry with fresh order
                        }
                        throw new Error(errorMsg);
                    }

                    const result = await submitResponse.json();
                    console.log('Order submitted:', result);

                    setSuccess(`Order placed! ${shares} shares at $${price.toFixed(3)}`);
                    setTimeout(() => {
                        onClose();
                        setSuccess(null);
                        setAmount('');
                        setSigningStep(null);
                    }, 2500);
                    return; // Success, exit retry loop

                } catch (err) {
                    console.error(`Trade error (attempt ${attempt + 1}):`, err);

                    // Check if retryable
                    if (err.message?.includes('invalid signature') && attempt < MAX_RETRIES) {
                        lastError = err;
                        continue;
                    }

                    // User cancelled - don't retry
                    if (err.code === 'ACTION_REJECTED' || err.code === 4001) {
                        setError('Transaction cancelled by user');
                        return;
                    }

                    lastError = err;
                    break; // Non-retryable error
                }
            }

            // All retries exhausted
            setError(lastError?.message || 'Order failed after retries');
        } finally {
            setLoading(false);
            setSigningStep(null);
        }
    };

    if (!isOpen) return null;

    const getButtonText = () => {
        if (!isConnected) return 'Connect Wallet First';
        if (!proxyWallet) return 'Setup Polymarket Wallet';
        if (!isTradingEnabled) return '🔒 Enable Trading First';
        if (signingStep === 'preparing') return 'Preparing order...';
        if (signingStep === 'signing') return '⏳ Sign in MetaMask...';
        if (signingStep === 'submitting') return 'Submitting order...';
        if (loading) return 'Processing...';
        return `Buy $${cost.toFixed(2)}`;
    };

    return (
        <div className="buy-popup-overlay" onClick={onClose}>
            <div className="buy-popup" onClick={e => e.stopPropagation()}>
                <button className="buy-popup-close" onClick={onClose}>×</button>

                <h2 className="buy-popup-title">Buy {side}</h2>
                <p className="buy-popup-question">{question}</p>

                <div className="buy-popup-price">
                    Best Ask: <strong>${price.toFixed(3)}</strong>
                    {vwapData && vwapData.vwap !== price && (
                        <span className="vwap-indicator">
                            {' '}→ Avg: <strong>${vwapData.vwap.toFixed(4)}</strong>
                        </span>
                    )}
                    {vwapLoading && <span className="vwap-loading"> ⏳</span>}
                </div>

                {proxyWallet && (
                    <div className="buy-popup-wallet">
                        Trading from: <code>{truncatedProxyWallet}</code>
                    </div>
                )}

                <div className="buy-popup-input-group">
                    <label>Shares to buy</label>
                    <input
                        type="number"
                        value={amount}
                        onChange={e => setAmount(e.target.value)}
                        placeholder="Enter amount..."
                        min="1"
                        step="1"
                        autoFocus
                        disabled={loading}
                    />
                </div>

                <div className="buy-popup-cost">
                    Total Cost: <strong>${cost.toFixed(2)} USDC</strong>
                    {vwapData?.total_shares && shares > 0 && (
                        <div className="vwap-shares">
                            ≈ {vwapData.total_shares.toFixed(2)} shares
                            {vwapData.levels_used > 1 && (
                                <span className="vwap-levels"> ({vwapData.levels_used} levels)</span>
                            )}
                        </div>
                    )}
                </div>

                {vwapData && !vwapData.is_fillable && (
                    <div className="buy-popup-warning">
                        ⚠️ Not enough liquidity! Only ${(cost - vwapData.remaining_usdc).toFixed(2)} available
                    </div>
                )}

                {error && <div className="buy-popup-error">{error}</div>}
                {success && <div className="buy-popup-success">{success}</div>}

                <div className="buy-popup-actions">
                    <button
                        className="buy-popup-cancel"
                        onClick={onClose}
                        disabled={loading}
                    >
                        Cancel
                    </button>
                    <button
                        className="buy-popup-confirm"
                        onClick={handleBuy}
                        disabled={loading || !shares || cost < 1 || !isConnected || !proxyWallet || !isTradingEnabled}
                    >
                        {getButtonText()}
                    </button>
                </div>


                {cost > 0 && cost < 1 && (
                    <div className="buy-popup-warning">Minimum order $1</div>
                )}
                {!isTradingEnabled && isConnected && proxyWallet && (
                    <div className="buy-popup-warning">Click "Enable Trading" in sidebar to start</div>
                )}
            </div>
        </div>
    );
};

export default BuyPopup;
