import { type ReactNode } from 'react';

interface PanelProps {
  children: ReactNode;
  className?: string;
  variant?: 'default' | 'red' | 'blue' | 'yellow';
  decoration?: 'circle' | 'square' | 'triangle' | 'none';
}

const variantStyles = {
  default: 'bg-bauhaus-white',
  red: 'bg-bauhaus-red text-white',
  blue: 'bg-bauhaus-blue text-white',
  yellow: 'bg-bauhaus-yellow text-bauhaus-black',
};

const decorationColors = {
  default: 'bg-bauhaus-red',
  red: 'bg-bauhaus-yellow',
  blue: 'bg-bauhaus-yellow',
  yellow: 'bg-bauhaus-red',
};

export function Panel({
  children,
  className = '',
  variant = 'default',
  decoration = 'circle',
}: PanelProps) {
  return (
    <div
      className={`
        relative
        border-4 border-bauhaus-black
        shadow-bauhaus-xl
        ${variantStyles[variant]}
        ${className}
      `}
    >
      {/* Bauhaus geometric decoration */}
      {decoration !== 'none' && (
        <div className="absolute -top-2 -right-2 w-4 h-4">
          {decoration === 'circle' && (
            <div className={`w-full h-full rounded-full ${decorationColors[variant]}`} />
          )}
          {decoration === 'square' && (
            <div className={`w-full h-full ${decorationColors[variant]}`} />
          )}
          {decoration === 'triangle' && (
            <div
              className={decorationColors[variant]}
              style={{
                width: 0,
                height: 0,
                borderLeft: '8px solid transparent',
                borderRight: '8px solid transparent',
                borderBottom: '16px solid currentColor',
              }}
            />
          )}
        </div>
      )}
      {children}
    </div>
  );
}
