'use client';

import { StepsBlock, TooltipDefinition } from '../../../lib/wiki/types';
import { MarkdownInline } from '../MarkdownInline';
import { useState } from 'react';
import { cn } from '../../../lib/utils';
import { ChevronDown, ChevronUp, ChevronLeft, ChevronRight } from 'lucide-react';
import { motion, AnimatePresence } from 'framer-motion';

interface StepsProps {
  block: StepsBlock;
  tooltips?: TooltipDefinition[];
}

export function Steps({ block, tooltips = [] }: StepsProps) {
  const [activeStep, setActiveStep] = useState<number>(0);
  const [isExpanded, setIsExpanded] = useState(false);

  const goToNextStep = () => {
    if (activeStep < block.items.length - 1) {
      setActiveStep(prev => prev + 1);
    }
  };

  const goToPrevStep = () => {
    if (activeStep > 0) {
      setActiveStep(prev => prev - 1);
    }
  };

  if (block.dynamic) {
    return (
      <div className="my-8 relative">
        {/* Expand/Collapse button */}
        <button
          onClick={() => setIsExpanded(!isExpanded)}
          className="absolute -top-2 right-0 z-10 p-1.5 rounded hover:bg-muted text-muted-foreground hover:text-foreground transition-colors"
          title={isExpanded ? 'Свернуть' : 'Показать все'}
        >
          {isExpanded ? (
            <ChevronUp className="h-4 w-4" />
          ) : (
            <ChevronDown className="h-4 w-4" />
          )}
        </button>

        <div className="relative w-full">
          {isExpanded ? (
            // Expanded mode - show all steps
            <div className="relative">
              {block.items.map((step, index) => {
                const isLast = index === block.items.length - 1;

                return (
                  <div key={index} className="relative flex gap-4 pb-8 last:pb-0">
                    {/* Vertical line connector */}
                    {!isLast && (
                      <div className="absolute left-[19px] top-[38px] bottom-0 w-[2px] border-l-2 border-dashed border-border" />
                    )}

                    {/* Step number circle */}
                    <div className="relative flex-shrink-0">
                      <div className="flex h-10 w-10 items-center justify-center rounded-full border-2 border-primary bg-background text-primary font-semibold shadow-sm">
                        {index + 1}
                      </div>
                    </div>

                    {/* Step content */}
                    <div className="flex-1 pt-1">
                      <h3 className="mb-2 text-lg font-semibold text-foreground">
                        <MarkdownInline text={step.title} tooltips={tooltips} />
                      </h3>
                      <div className="text-muted-foreground">
                        <MarkdownInline text={step.description} tooltips={tooltips} />
                      </div>
                    </div>
                  </div>
                );
              })}
            </div>
          ) : (
            // Dynamic mode - show one step at a time with navigation
            <div className="relative">
              <AnimatePresence mode="wait">
                <motion.div
                  key={activeStep}
                  initial={{ opacity: 0, x: 20 }}
                  animate={{ opacity: 1, x: 0 }}
                  exit={{ opacity: 0, x: -20 }}
                  transition={{ duration: 0.3, ease: [0.4, 0, 0.2, 1] }}
                  className="flex gap-4"
                >
                  {/* Step number circle */}
                  <div className="relative flex-shrink-0">
                    <motion.div
                      initial={{ scale: 0.9 }}
                      animate={{ scale: 1 }}
                      transition={{ duration: 0.3 }}
                      className="flex h-10 w-10 items-center justify-center rounded-full border-2 border-primary bg-primary text-primary-foreground font-semibold shadow-lg"
                    >
                      {activeStep + 1}
                    </motion.div>
                  </div>

                  {/* Step content */}
                  <div className="flex-1 pt-1">
                    <h3 className="mb-2 text-lg font-semibold text-foreground">
                      <MarkdownInline text={block.items[activeStep].title} tooltips={tooltips} />
                    </h3>
                    <div className="text-muted-foreground">
                      <MarkdownInline text={block.items[activeStep].description} tooltips={tooltips} />
                    </div>
                  </div>
                </motion.div>
              </AnimatePresence>

              {/* Navigation controls */}
              <div className="mt-6 flex items-center justify-between gap-4">
                {/* Previous button */}
                <button
                  onClick={goToPrevStep}
                  disabled={activeStep === 0}
                  className={cn(
                    'p-2 rounded-lg transition-all duration-200',
                    activeStep === 0
                      ? 'opacity-30 cursor-not-allowed'
                      : 'hover:bg-muted text-muted-foreground hover:text-foreground'
                  )}
                  aria-label="Previous step"
                >
                  <ChevronLeft className="h-5 w-5" />
                </button>

                {/* Progress indicator */}
                <div className="flex items-center justify-center gap-2 flex-1">
                  {block.items.map((_, index) => (
                    <button
                      key={index}
                      onClick={() => setActiveStep(index)}
                      className={cn(
                        'h-1.5 rounded-full transition-all duration-300 cursor-pointer hover:bg-primary/70',
                        index === activeStep
                          ? 'w-8 bg-primary'
                          : 'w-1.5 bg-border'
                      )}
                      aria-label={`Go to step ${index + 1}`}
                    />
                  ))}
                </div>

                {/* Next button */}
                <button
                  onClick={goToNextStep}
                  disabled={activeStep === block.items.length - 1}
                  className={cn(
                    'p-2 rounded-lg transition-all duration-200',
                    activeStep === block.items.length - 1
                      ? 'opacity-30 cursor-not-allowed'
                      : 'hover:bg-muted text-muted-foreground hover:text-foreground'
                  )}
                  aria-label="Next step"
                >
                  <ChevronRight className="h-5 w-5" />
                </button>
              </div>

              {/* Step counter */}
              <div className="mt-2 text-center text-sm text-muted-foreground">
                Шаг {activeStep + 1} из {block.items.length}
              </div>
            </div>
          )}
        </div>
      </div>
    );
  }

  // Static mode (original behavior with optional highlight)
  return (
    <div className="my-8">
      <div className="relative">
        {block.items.map((step, index) => {
          const isLast = index === block.items.length - 1;
          const isHighlighted = step.highlight;

          return (
            <div
              key={index}
              className="relative flex gap-4 pb-8 last:pb-0 transition-all duration-300"
            >
              {/* Vertical line connector */}
              {!isLast && (
                <div
                  className={cn(
                    'absolute left-[19px] top-[38px] bottom-0 w-[2px] border-l-2 transition-colors duration-300',
                    isHighlighted
                      ? 'border-primary border-solid'
                      : 'border-dashed border-border'
                  )}
                />
              )}

              {/* Step number circle */}
              <div className="relative flex-shrink-0">
                <div
                  className={cn(
                    'flex h-10 w-10 items-center justify-center rounded-full border-2 font-semibold shadow-sm transition-all duration-300',
                    isHighlighted
                      ? 'border-primary bg-primary text-primary-foreground scale-110 shadow-lg'
                      : 'border-primary bg-background text-primary'
                  )}
                >
                  {index + 1}
                </div>
              </div>

              {/* Step content */}
              <div className="flex-1 pt-1">
                <h3
                  className={cn(
                    'mb-2 text-lg font-semibold transition-colors duration-300',
                    isHighlighted ? 'text-foreground' : 'text-foreground'
                  )}
                >
                  <MarkdownInline text={step.title} tooltips={tooltips} />
                </h3>
                <div
                  className={cn(
                    'transition-colors duration-300',
                    isHighlighted
                      ? 'text-foreground/90'
                      : 'text-muted-foreground'
                  )}
                >
                  <MarkdownInline text={step.description} tooltips={tooltips} />
                </div>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
