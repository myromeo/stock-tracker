CREATE EXTENSION IF NOT EXISTS timescaledb;

CREATE TABLE IF NOT EXISTS prices (
    symbol      TEXT        NOT NULL,
    ts          TIMESTAMPTZ NOT NULL,
    open        DOUBLE PRECISION,
    high        DOUBLE PRECISION,
    low         DOUBLE PRECISION,
    close       DOUBLE PRECISION,
    volume      BIGINT,
    PRIMARY KEY (symbol, ts)
);

SELECT create_hypertable('prices', 'ts', if_not_exists => TRUE);

CREATE INDEX IF NOT EXISTS idx_prices_symbol_ts ON prices (symbol, ts DESC);

CREATE TABLE IF NOT EXISTS predictions (
    symbol          TEXT        NOT NULL,
    ts              TIMESTAMPTZ NOT NULL,   -- date being forecast
    yhat            DOUBLE PRECISION,
    yhat_lower      DOUBLE PRECISION,
    yhat_upper      DOUBLE PRECISION,
    generated_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (symbol, ts, generated_at)
);

SELECT create_hypertable('predictions', 'ts', if_not_exists => TRUE);

CREATE INDEX IF NOT EXISTS idx_predictions_symbol_generated
    ON predictions (symbol, generated_at DESC);
