---
title: Lab Automation
description: "Deployment template and lab setup scripts for the Claims MicroHack"
---

# Lab Automation

This folder contains the automated lab deployment configuration for the ClaimSight Claims MicroHack.

## Files

* **`deploy-lab.ps1`** — Deployment script that provisions Azure resources (Storage, AI Foundry, Search, Functions) and uploads claim data to blob storage.
* **`lab-defaults.json`** — Lab configuration file specifying deployment type, preferred Azure regions, and estimated daily costs.
* **`azuredeploy.json`** — ARM template defining all Azure infrastructure resources.

## Usage

The platform runs `deploy-lab.ps1` with these parameters:

```powershell
.\deploy-lab.ps1 `
  -DeploymentType resourcegroup `
  -SubscriptionId <subscription-id> `
  -ResourceGroupName <resource-group-name>
```

Supported deployment types:

* `resourcegroup` — Platform pre-creates the resource group; script deploys into it.
* `subscription` — Script generates a deterministic resource group name and creates it.
* `resourcegroup-with-subscriptionowner` — Platform pre-creates the resource group with subscription-owner role.

## Outputs

The script emits credentials and resource details (via `Publish-HackboxCredential`) that the platform captures and makes available as environment variables during the challenges:

* Azure resource names (storage account, Search service, AI Foundry project)
* API keys and connection strings
* Blob container names and Search index names

See [Root README](../README.md) for challenge instructions.
