import React from 'react';
import './FilterPill.css';

// Hex colors for each variant with their 25% and 100% opacity versions
const colorConfig = {
    hot: { solid: '#FF073A', fill: 'rgba(255, 7, 58, 0.25)', fillActive: '#FF073A' },
    whale: { solid: '#04D9FF', fill: 'rgba(4, 217, 255, 0.25)', fillActive: '#04D9FF' },
    fresh: { solid: '#39FF14', fill: 'rgba(57, 255, 20, 0.25)', fillActive: '#39FF14' },
    gain: { solid: '#4ade80', fill: 'rgba(74, 222, 128, 0.25)', fillActive: '#4ade80' },
    new: { solid: '#FF9500', fill: 'rgba(255, 149, 0, 0.25)', fillActive: '#FF9500' },
    ending: { solid: '#A855F7', fill: 'rgba(168, 85, 247, 0.25)', fillActive: '#A855F7' },
    gray: { solid: '#B8B9BB', fill: 'rgba(184, 185, 187, 0.25)', fillActive: '#B8B9BB' },
};

const FilterPill = ({ label, count, variant = 'gray', icon, active = false, onClick, size = 'normal', noHover = false }) => {
    const config = colorConfig[variant] || colorConfig.gray;
    // Use solid fill when active, otherwise 25% opacity
    const bgColor = active ? config.fillActive : config.fill;

    return (
        <button
            className={`filter-pill ${active ? 'active' : ''} ${size === 'small' ? 'filter-pill-small' : ''} ${noHover ? 'no-hover' : ''}`}
            style={{
                '--pill-accent': config.solid,
                '--pill-bg': config.fill,
                borderColor: config.solid,
                backgroundColor: bgColor,
            }}
            onClick={onClick}
        >
            {icon && <span className="filter-pill-icon">{icon}</span>}
            <span className="filter-pill-label">{label}</span>
            {count !== undefined && <span className="filter-pill-count">{count}</span>}
        </button>
    );
};

export default FilterPill;
