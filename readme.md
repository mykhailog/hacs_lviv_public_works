# Lviv Public Works

## About
This integration add ability to receive notifications about  [Lviv City public works](https://1580.lviv.ua/) in Home Assistant.

Інтеграція, що дозволяє отримувати сповіщення про ремонтні роботи та аварійні відключення у м. Львова в Home Assistant.

## Installation
### HACS
If you use [HACS](https://hacs.xyz/) you can install and update this component.
1. Go into HACS -> CUSTOM REPOSITORIES and add url: https://github.com/mykhailog/hacs_lviv_public_works with type "integration"
2. Go to integration, search "lviv_public_works" and click *Install*.
### Manual
Download and unzip or clone this repository and copy `custom_components/lviv_public_works/` to your configuration directory of Home Assistant, e.g. `~/.homeassistant/custom_components/`.

In the end your file structure should look like that:
```
~/.homeassistant/custom_components/lviv_public_works/__init__.py
~/.homeassistant/custom_components/lviv_public_works/manifest.json
~/.homeassistant/custom_components/lviv_public_works/sensor.py
```

## Configuration
To use integration in your installation, add the following to your `configuration.yaml` file:
```yaml
# Example configuration.yaml entry
lviv_public_works:
  street: Стрілецька
  house: 1
```

## Configuration Variables
key | description | example |note
:--- | :--- | :--- | :---
**platform (Required)** | lviv_public_works
**street (Required)** | Your street name. |Стрілецька | [Street list](https://1580.lviv.ua/perelik-vsi/)
**house (Optional)** | Your house number | 1 
**scan_interval (Optional)** | Defines the update interval of the feeds. | 3600

***


## Examples
Lviv Public Works events can be used out of the box to trigger automation actions, e.g.:

```yaml
automation:
  - alias: Send notification when new public work is available
    trigger:
      event_type: lviv_public_works_event
      platform: event
    action:
      data_template:
        message: >-
          {{trigger.event.data.content}}  {{trigger.event.data.start_date}} -
          {{trigger.event.data.end_date}}
        title: '⚠️{{trigger.event.data.title}}'
      service: notify.notify

```
