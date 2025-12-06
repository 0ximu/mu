import { type ReactNode } from 'react';

type BadgeVariant = 'red' | 'blue' | 'yellow' | 'gray';
type BadgeShape = 'square' | 'pill';

interface BadgeProps {
  variant?: BadgeVariant;
  shape?: BadgeShape;
  children: ReactNode;
  className?: string;
}

const variantStyles: Record<BadgeVariant, string> = {
  red: 'bg-bauhaus-red text-white',
  blue: 'bg-bauhaus-blue text-white',
  yellow: 'bg-bauhaus-yellow text-bauhaus-black',
  gray: 'bg-bauhaus-muted text-bauhaus-black',
};

const shapeStyles: Record<BadgeShape, string> = {
  square: 'rounded-none',
  pill: 'rounded-full',
};

export function Badge({
  variant = 'blue',
  shape = 'square',
  children,
  className = '',
}: BadgeProps) {
  return (
    <span
      className={`
        inline-flex items-center justify-center
        px-2 py-0.5
        text-xs font-bold uppercase tracking-wider
        ${variantStyles[variant]}
        ${shapeStyles[shape]}
        ${className}
      `}
    >
      {children}
    </span>
  );
}
