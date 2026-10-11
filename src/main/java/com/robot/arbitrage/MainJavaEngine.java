
package com.robot.arbitrage;

import java.util.concurrent.TimeUnit;

/**
 * Free Arbitrage Mesh — Java Signal Monitor
 *
 * The default mode uses example values for demonstration.
 * No real market feed or order execution is implemented here.
 */
public final class MainJavaEngine {

    private static final long DEFAULT_INBOUND_PRICE = 9_500L;
    private static final long DEFAULT_FAIR_VALUE = 10_100L;
    private static final long DEFAULT_INTERVAL_SECONDS = 10L;

    private MainJavaEngine() {
        // Application entry point only.
    }

    public static void main(String[] args) {
        String mode = System.getenv().getOrDefault(
                "JAVA_ENGINE_MODE",
                "simulation"
        ).trim().toLowerCase();

        if (!"simulation".equals(mode)) {
            System.err.println(
                    "Java engine stopped: only simulation mode is "
                    + "implemented. A live data adapter and execution "
                    + "system have not been configured."
            );
            System.exit(2);
            return;
        }

        long inboundPrice = readLongEnvironment(
                "SIMULATED_INBOUND_PRICE_MINOR",
                DEFAULT_INBOUND_PRICE
        );

        long fairValue = readLongEnvironment(
                "SIMULATED_FAIR_VALUE_MINOR",
                DEFAULT_FAIR_VALUE
        );

        long intervalSeconds = Math.max(
                1L,
                readLongEnvironment(
                        "JAVA_ENGINE_INTERVAL_SECONDS",
                        DEFAULT_INTERVAL_SECONDS
                )
        );

        System.out.println(
                "Free Arbitrage Mesh Java signal monitor started."
        );
        System.out.println(
                "Mode: SIMULATION — example prices only; no orders submitted."
        );

        Runtime.getRuntime().addShutdownHook(
                new Thread(
                        () -> System.out.println(
                                "Java signal monitor shutting down."
                        ),
                        "java-engine-shutdown"
                )
        );

        while (!Thread.currentThread().isInterrupted()) {
            try {
                boolean signal = NanosecondExecutionEngine.evaluateSignal(
                        inboundPrice,
                        fairValue
                );

                long difference = fairValue - inboundPrice;

                System.out.printf(
                        "SIMULATION | inbound=%d | fair_value=%d "
                                + "| difference=%d | signal=%s%n",
                        inboundPrice,
                        fairValue,
                        difference,
                        signal ? "TRIGGERED" : "NOT_TRIGGERED"
                );

                if (signal) {
                    System.out.println(
                            "Signal detected. No order was executed."
                    );
                }

                TimeUnit.SECONDS.sleep(intervalSeconds);

            } catch (InterruptedException exception) {
                Thread.currentThread().interrupt();
                break;

            } catch (RuntimeException exception) {
                System.err.println(
                        "Signal evaluation failed: "
                                + exception.getMessage()
                );

                try {
                    TimeUnit.SECONDS.sleep(5);
                } catch (InterruptedException interrupted) {
                    Thread.currentThread().interrupt();
                    break;
                }
            }
        }

        System.out.println("Java signal monitor stopped.");
    }

    private static long readLongEnvironment(
            String variable,
            long defaultValue
    ) {
        String raw = System.getenv(variable);

        if (raw == null || raw.isBlank()) {
            return defaultValue;
        }

        try {
            return Long.parseLong(raw.trim());
        } catch (NumberFormatException exception) {
            throw new IllegalArgumentException(
                    "Invalid integer in environment variable: " + variable,
                    exception
            );
        }
    }
}
