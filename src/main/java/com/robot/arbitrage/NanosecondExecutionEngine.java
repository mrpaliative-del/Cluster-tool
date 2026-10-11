
package com.robot.arbitrage;

import java.math.BigInteger;

/**
 * Free Arbitrage Mesh — Signal Evaluation Engine
 *
 * Evaluates a price difference using safe Java arithmetic.
 * This class does not submit orders, access exchanges, or guarantee profit.
 */
public final class NanosecondExecutionEngine {

    private static final long DEFAULT_THRESHOLD_MINOR_UNITS = 500L;

    private NanosecondExecutionEngine() {
        // Utility class.
    }

    /**
     * Returns true when the calculated fair value exceeds the inbound
     * price by more than the configured threshold.
     *
     * All values must use the same currency and unit, such as kobo.
     */
    public static boolean evaluateSignal(
            long inboundPrice,
            long calculatedFairValue
    ) {
        return evaluateSignal(
                inboundPrice,
                calculatedFairValue,
                configuredThreshold()
        );
    }

    /**
     * Explicit-threshold overload, useful for testing.
     */
    public static boolean evaluateSignal(
            long inboundPrice,
            long calculatedFairValue,
            long threshold
    ) {
        if (inboundPrice < 0 || calculatedFairValue < 0) {
            throw new IllegalArgumentException(
                    "Prices must not be negative."
            );
        }

        if (threshold < 0) {
            throw new IllegalArgumentException(
                    "Threshold must not be negative."
            );
        }

        BigInteger difference = BigInteger.valueOf(calculatedFairValue)
                .subtract(BigInteger.valueOf(inboundPrice));

        return difference.compareTo(BigInteger.valueOf(threshold)) > 0;
    }

    private static long configuredThreshold() {
        String configured = System.getenv("PRICE_SIGNAL_THRESHOLD_MINOR");

        if (configured == null || configured.isBlank()) {
            return DEFAULT_THRESHOLD_MINOR_UNITS;
        }

        try {
            long threshold = Long.parseLong(configured.trim());

            if (threshold < 0) {
                throw new IllegalArgumentException(
                        "PRICE_SIGNAL_THRESHOLD_MINOR must not be negative."
                );
            }

            return threshold;
        } catch (NumberFormatException exception) {
            throw new IllegalArgumentException(
                    "PRICE_SIGNAL_THRESHOLD_MINOR must be a valid integer.",
                    exception
            );
        }
    }
}
