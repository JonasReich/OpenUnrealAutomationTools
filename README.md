
# Open Unreal Automation Tools

![](./Resources/oua_wide.png)

The Open Unreal Automation Tools are lightweight scripts for automating Unreal Engine processes like builds, automation tests, etc.

## Technology

The tools in this repository are mostly python scripts with some utility Windows batch scripts mixed in for convenience (e.g. double click to install python modules, etc). Dependencies to non-standard third party libraries were avoided with the following exceptions:
- vswhere: Used to find Visual Studio installations
- pytest: Used to test some of the python modules
- requests: For web connections with build services like TeamCity, UE tools distributors like the VS marketplace, etc
- alive_progress: Visualizing some of the longer running processes like logparsing
- semver: Foundation for Unreal and project version detections

Previous versions also included some PowerShell utilities, but I figured this is all far more maintainable by focusing and comitting on a single environment, so they were all removed in January 2026.

Like Epics UAT, some of the tools assume the usage of Perforce in commercial scale environments, but my hobby projects and the actual versioning of these scripts run in git, so I try to support both for most of the utilities.

## Development

The tools are developed alongside with the [Open Unreal Utiltiies plugin](https://github.com/JonasReich/OpenUnrealUtilities).
Many of the utilities here are used and improved at Grimlore Games for build automation scripting together with additional proprietary tools.

At this point of time, this project is not ready for contributions, but I'm planning to enable pull requests eventually.

See also [Open Unreal Sample Project](https://github.com/JonasReich/OpenUnrealSampleProject).

## License

This project is licensed under the [MIT license](./LICENSE.md).
