# Installation

Docker Compose is currently the recommended way to run the FERPEK Lens server.

## Requirements

- Docker
- Docker Compose
- Git

## Clone FERPEK Lens

Clone the FERPEK Lens repository and enter the project directory.

## Configuration

Copy `.env.example` to `.env` before starting the application.

Review the configuration before exposing FERPEK Lens outside a development environment.

## Start FERPEK Lens

Start the Docker Compose stack with a build.

The server and web interface should then be available through their configured ports.

By default, the web interface is available on port `5173`.

## First login

On first use, FERPEK Lens will ask you to create the initial administrator account.

After creating the administrator account, continue with **Add your first host**.
