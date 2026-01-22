import React, { createContext, useContext, useState, useEffect, useCallback } from 'react';
import { BrowserProvider } from 'ethers';

const POLYGON_CHAIN_ID = '0x89'; // 137 in hex
const POLYGON_CHAIN_CONFIG = {
    chainId: POLYGON_CHAIN_ID,
    chainName: 'Polygon Mainnet',
    nativeCurrency: { name: 'MATIC', symbol: 'MATIC', decimals: 18 },
    rpcUrls: ['https://polygon-rpc.com'],
    blockExplorerUrls: ['https://polygonscan.com/'],
};

const WalletContext = createContext(null);

export const useWallet = () => {
    const ctx = useContext(WalletContext);
    if (!ctx) throw new Error('useWallet must be used within WalletProvider');
    return ctx;
};

export const WalletProvider = ({ children }) => {
    const [address, setAddress] = useState(null);
    const [proxyWallet, setProxyWallet] = useState(null);
    const [profileData, setProfileData] = useState(null);
    const [isConnecting, setIsConnecting] = useState(false);
    const [needsProxyWallet, setNeedsProxyWallet] = useState(false);
    const [error, setError] = useState(null);

    // L2 API Credentials for trading
    const [userCredentials, setUserCredentials] = useState(null);
    const [isDerivingCredentials, setIsDerivingCredentials] = useState(false);

    const truncateAddress = (addr) =>
        addr ? `${addr.slice(0, 6)}...${addr.slice(-4)}` : '';

    const switchToPolygon = async () => {
        try {
            await window.ethereum.request({
                method: 'wallet_switchEthereumChain',
                params: [{ chainId: POLYGON_CHAIN_ID }],
            });
        } catch (switchError) {
            if (switchError.code === 4902) {
                await window.ethereum.request({
                    method: 'wallet_addEthereumChain',
                    params: [POLYGON_CHAIN_CONFIG],
                });
            } else {
                throw switchError;
            }
        }
    };

    const fetchProxyWallet = async (walletAddress) => {
        try {
            // Use backend proxy to bypass CORS
            const response = await fetch(`/api/polymarket-profile?address=${walletAddress}`);
            if (!response.ok) {
                setNeedsProxyWallet(true);
                setProxyWallet(null);
                return null;
            }
            const data = await response.json();
            if (data.proxyWallet) {
                setProxyWallet(data.proxyWallet);
                setProfileData(data);
                setNeedsProxyWallet(false);
                localStorage.setItem('proxyWallet', data.proxyWallet);
                console.log('Proxy wallet found:', data.proxyWallet);
                return data.proxyWallet;
            } else {
                setNeedsProxyWallet(true);
                setProxyWallet(null);
                return null;
            }
        } catch (err) {
            console.error('Failed to fetch proxy wallet:', err);
            setNeedsProxyWallet(true);
            setProxyWallet(null);
            return null;
        }
    };

    // Derive L2 API credentials by signing ClobAuth message
    const deriveApiCredentials = useCallback(async () => {
        if (!address || !window.ethereum) {
            setError('Wallet not connected');
            return false;
        }

        setIsDerivingCredentials(true);
        setError(null);

        try {
            // 1. Get ClobAuth message structure from backend
            const msgResponse = await fetch(`/api/auth/clob-message?address=${address}`);
            if (!msgResponse.ok) {
                throw new Error('Failed to get auth message');
            }
            const { domain, types, message, timestamp, nonce } = await msgResponse.json();

            // 2. Sign with MetaMask (EIP-712)
            const provider = new BrowserProvider(window.ethereum);
            const signer = await provider.getSigner();

            // Remove EIP712Domain from types (ethers v6 adds it automatically)
            const signingTypes = { ...types };
            delete signingTypes.EIP712Domain;

            const signature = await signer.signTypedData(domain, signingTypes, message);
            console.log('ClobAuth signed:', signature.slice(0, 20) + '...');

            // 3. Derive API credentials using signature
            const deriveResponse = await fetch('/api/auth/derive-api-key', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    address: address,
                    signature: signature,
                    timestamp: timestamp,
                    nonce: nonce
                })
            });

            if (!deriveResponse.ok) {
                const errorData = await deriveResponse.json();
                throw new Error(errorData.detail || 'Failed to derive API key');
            }

            const credentials = await deriveResponse.json();

            // 4. Save credentials
            setUserCredentials(credentials);
            localStorage.setItem(`polymarket_creds_${address}`, JSON.stringify(credentials));
            console.log('L2 credentials derived successfully');

            return true;
        } catch (err) {
            console.error('Failed to derive credentials:', err);
            setError(err.message || 'Failed to enable trading');
            return false;
        } finally {
            setIsDerivingCredentials(false);
        }
    }, [address]);

    const connectWallet = useCallback(async () => {
        if (!window.ethereum) {
            setError('MetaMask не установлен');
            return false;
        }

        setIsConnecting(true);
        setError(null);
        setNeedsProxyWallet(false);

        try {
            await switchToPolygon();
            const provider = new BrowserProvider(window.ethereum);
            const signer = await provider.getSigner();
            const addr = await signer.getAddress();
            setAddress(addr);
            localStorage.setItem('walletConnected', 'true');
            localStorage.setItem('walletAddress', addr);

            // Fetch proxy wallet from Polymarket
            await fetchProxyWallet(addr);

            // Try to load saved credentials
            const savedCreds = localStorage.getItem(`polymarket_creds_${addr}`);
            if (savedCreds) {
                try {
                    setUserCredentials(JSON.parse(savedCreds));
                    console.log('Loaded saved L2 credentials');
                } catch (e) {
                    console.warn('Failed to parse saved credentials');
                }
            }

            return true;
        } catch (err) {
            console.error('Wallet connection error:', err);
            setError(err.message || 'Ошибка подключения');
            return false;
        } finally {
            setIsConnecting(false);
        }
    }, []);

    const disconnectWallet = useCallback(() => {
        setAddress(null);
        setProxyWallet(null);
        setProfileData(null);
        setUserCredentials(null);
        setNeedsProxyWallet(false);
        setError(null);
        localStorage.removeItem('walletConnected');
        localStorage.removeItem('walletAddress');
        localStorage.removeItem('proxyWallet');
        if (address) {
            localStorage.removeItem(`polymarket_creds_${address}`);
        }
    }, [address]);

    // Auto-reconnect on page load
    useEffect(() => {
        const wasConnected = localStorage.getItem('walletConnected') === 'true';
        if (wasConnected && window.ethereum) {
            connectWallet();
        }
    }, [connectWallet]);

    // Listen for account/chain changes
    useEffect(() => {
        if (!window.ethereum) return;

        const handleAccountsChanged = (accounts) => {
            if (accounts.length > 0) {
                setAddress(accounts[0]);
                fetchProxyWallet(accounts[0]);
                // Load credentials for new account
                const savedCreds = localStorage.getItem(`polymarket_creds_${accounts[0]}`);
                if (savedCreds) {
                    try {
                        setUserCredentials(JSON.parse(savedCreds));
                    } catch (e) {
                        setUserCredentials(null);
                    }
                } else {
                    setUserCredentials(null);
                }
            } else {
                disconnectWallet();
            }
        };

        const handleChainChanged = () => {
            if (address) connectWallet();
        };

        window.ethereum.on('accountsChanged', handleAccountsChanged);
        window.ethereum.on('chainChanged', handleChainChanged);

        return () => {
            window.ethereum.removeListener('accountsChanged', handleAccountsChanged);
            window.ethereum.removeListener('chainChanged', handleChainChanged);
        };
    }, [address, connectWallet, disconnectWallet]);

    const value = {
        address,
        truncatedAddress: truncateAddress(address),
        proxyWallet,
        truncatedProxyWallet: truncateAddress(proxyWallet),
        profileData,
        isConnecting,
        isConnected: !!address,
        needsProxyWallet,
        error,
        connectWallet,
        disconnectWallet,
        fetchProxyWallet,
        // L2 Credentials
        userCredentials,
        isDerivingCredentials,
        isTradingEnabled: !!userCredentials,
        deriveApiCredentials,
    };

    return (
        <WalletContext.Provider value={value}>
            {children}
        </WalletContext.Provider>
    );
};
