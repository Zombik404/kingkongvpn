-- Runs once on first container start (development only).
CREATE EXTENSION IF NOT EXISTS citext;
CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- Separate database for the backend test suite.
CREATE DATABASE globalvpn_test;
\connect globalvpn_test
CREATE EXTENSION IF NOT EXISTS citext;
CREATE EXTENSION IF NOT EXISTS pgcrypto;
