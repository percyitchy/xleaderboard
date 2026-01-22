import React from 'react';
import { ShaderGradient, ShaderGradientCanvas } from 'shadergradient';

const DynamicBackground = () => (
    <div style={{
        position: 'fixed',
        top: 0,
        left: 0,
        width: '100vw',
        height: '100vh',
        zIndex: -1,
        pointerEvents: 'none'
    }}>
        <ShaderGradientCanvas>
            <ShaderGradient
                animate="on"
                brightness={1}
                cAzimuthAngle={0}
                cDistance={2.8}
                cPolarAngle={80}
                cameraZoom={9.1}
                color1="#493459"
                color2="#7160b7"
                color3="#212121"
                envPreset="city"
                grain="on"
                lightType="3d"
                positionX={0}
                positionY={0}
                positionZ={0}
                reflection={0.1}
                rotationX={50}
                rotationY={0}
                rotationZ={-60}
                type="waterPlane"
                uDensity={1.4}
                uSpeed={0.1}
                uStrength={2.2}
                uTime={8}
            />
        </ShaderGradientCanvas>
        {/* Dark overlay to reduce brightness by 50% */}
        <div style={{
            position: 'absolute',
            top: 0,
            left: 0,
            width: '100%',
            height: '100%',
            backgroundColor: 'rgba(0, 0, 0, 0.7)',
            pointerEvents: 'none'
        }} />
    </div>
);

export default DynamicBackground;

