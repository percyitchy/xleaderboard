import React from 'react';
import './GlassCard.css';

const GlassCard = React.forwardRef(({ children, className = '', onClick, ...props }, ref) => (
    <div
        ref={ref}
        className={`glass-card ${className}`}
        onClick={onClick}
        {...props}
    >
        {children}
    </div>
));

GlassCard.displayName = 'GlassCard';

export default GlassCard;
