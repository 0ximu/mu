import { forwardRef, type InputHTMLAttributes } from 'react';

interface SliderProps extends Omit<InputHTMLAttributes<HTMLInputElement>, 'type'> {
  label?: string;
  showValue?: boolean;
}

export const Slider = forwardRef<HTMLInputElement, SliderProps>(
  ({ label, showValue = true, className = '', value, ...props }, ref) => {
    return (
      <div className="flex flex-col gap-2">
        {(label || showValue) && (
          <div className="flex justify-between items-center">
            {label && (
              <label className="font-bauhaus-label text-bauhaus-black">
                {label}
              </label>
            )}
            {showValue && (
              <span className="font-bold text-bauhaus-black tabular-nums">
                {value}
              </span>
            )}
          </div>
        )}
        <input
          ref={ref}
          type="range"
          value={value}
          className={`
            w-full h-3
            bg-bauhaus-muted
            border-2 border-bauhaus-black
            appearance-none
            cursor-pointer
            [&::-webkit-slider-thumb]:appearance-none
            [&::-webkit-slider-thumb]:w-5
            [&::-webkit-slider-thumb]:h-5
            [&::-webkit-slider-thumb]:bg-bauhaus-red
            [&::-webkit-slider-thumb]:border-2
            [&::-webkit-slider-thumb]:border-bauhaus-black
            [&::-webkit-slider-thumb]:cursor-pointer
            [&::-webkit-slider-thumb]:hover:bg-bauhaus-yellow
            [&::-moz-range-thumb]:w-5
            [&::-moz-range-thumb]:h-5
            [&::-moz-range-thumb]:bg-bauhaus-red
            [&::-moz-range-thumb]:border-2
            [&::-moz-range-thumb]:border-bauhaus-black
            [&::-moz-range-thumb]:cursor-pointer
            [&::-moz-range-thumb]:hover:bg-bauhaus-yellow
            ${className}
          `}
          {...props}
        />
      </div>
    );
  }
);

Slider.displayName = 'Slider';
