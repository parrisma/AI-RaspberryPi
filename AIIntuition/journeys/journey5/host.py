from copy import deepcopy
from typing import List
from AIIntuition.journeys.journey5.datacenter import DataCenter
from AIIntuition.journeys.journey5.core import Core
from AIIntuition.journeys.journey5.compute import Compute
from AIIntuition.journeys.journey5.task import Task
from AIIntuition.journeys.journey5.infrnditer import InfRndIter
from AIIntuition.journeys.journey5.OutOfMemoryException import OutOfMemoryException
from AIIntuition.journeys.journey5.FailedToCompleteException import FailedToCompleteException
from AIIntuition.journeys.journey5.log import Log
from AIIntuition.journeys.journey5.event import HostEvent
from AIIntuition.journeys.journey5.util import Util
from AIIntuition.journeys.journey5.cputype import CPUType
from AIIntuition.journeys.journey5.computeprofile import ComputeProfile


class Host(Compute):

    def __init__(self,
                 data_center: DataCenter,
                 compute_profile: ComputeProfile):
        """
        Create a new random host according to the defined probability distributions
        Data Center, Type & capacity.
        """
        self._data_center = data_center
        self._id = Compute.gen_compute_id(self)
        self._core = compute_profile.core
        self._memory_available = compute_profile.mem
        self._tasks = {}
        self._inf_task_iter = None  # The infinite iterate to use when running associated tasks.
        self._curr_mem = 0
        self._curr_comp = 0
        Log.log_event(HostEvent(HostEvent.HostEventType.INSTANTIATE, self), '')
        return

    @property
    def data_center(self) -> DataCenter.CountryCode:
        return self._data_center.country_mnemonic

    @property
    def name(self) -> str:
        return ''.join((self.data_center, '_', self._id))

    @property
    def id(self) -> str:
        return deepcopy(self._id)

    @property
    def type(self) -> CPUType:
        return deepcopy(self._core.core_type)

    @property
    def core_count(self) -> int:
        return deepcopy(self._core.num_core)

    @property
    def max_memory(self) -> int:
        return deepcopy(self._memory_available.size)

    @property
    def current_memory(self) -> int:
        """
        The current memory utilisation
        :return: The current memory utilisation in MB
        """
        return deepcopy(self._curr_mem)

    @property
    def max_compute(self) -> float:
        """
        The maximum amount of compute capability of the given compute resource
        :return: The max compute
        """
        # Num Core is the number of compute units of the current core type as such it is the max compute
        # capability.
        return deepcopy(self._core.num_core)

    @property
    def current_compute(self) -> float:
        """
        The current compute utilisation
        :return: The current compute utilisation
        """
        return deepcopy(self._curr_comp)

    def associate_task(self,
                       task: Task) -> None:
        """
        Associate the given task with this host such that the host will execute the task during it's run
        cycle.
        :param task: The task to associate with the Host
        """
        self._tasks[task.id] = task
        self.__update_inf_iter()
        Log.log_event(HostEvent(HostEvent.HostEventType.ASSOCIATE, self, task), '')
        return

    def disassociate_task(self,
                          task: Task) -> None:
        """
        Dis-Associate the given task with this host such that the host will NOT execute the task during it's run
        cycle.
        :param task: The task to associate with the Host
        """
        if task.id not in self._tasks:
            raise ValueError(task.id + ' is not associated with host :' + self.id)

        del self._tasks[task.id]
        self.__update_inf_iter()
        Log.log_event(HostEvent(HostEvent.HostEventType.DISASSOCIATE, self, task), '')

        return

    @property
    def num_associated_task(self) -> int:
        """
        The number of tasks currently associated with this Compute
        :return: The number of associated tasks.
        """
        return len(self._tasks)

    def run_next_task(self,
                      gmt_hour_of_day: int) -> None:
        """
        Randomly pick a task from the list of associated and run it - eventually all tasks will be run. It is possible
        that tasks will not all be run an equal number of times.
        :param gmt_hour_of_day: The gmt hour of day at which the task is being executed
        """
        local_hour_of_day = self._data_center.local_hour_of_day(gmt_hour_of_day)

        if len(self._tasks) == 0:
            print("No tasks to run on Host:" + self.id)
            return

        # Get next (random) task to run
        task_to_run = self.__next_task_to_execute()

        # Get current & required demand - return current resources
        cd, cc, ct, md, cm = task_to_run.resource_demand(local_hour_of_day)
        self._curr_comp = max(0, self._curr_comp - cc)  # Pay back current compute use
        self._curr_mem = max(0, self._curr_mem - cm)  # Pay back current mem use

        if task_to_run.done:
            if task_to_run.compute_deficit > 0:
                e = FailedToCompleteException(task_to_run, self)
                task_to_run.task_failure(e)
                self.disassociate_task(task_to_run)
                raise e
            else:
                Log.log_event(HostEvent(HostEvent.HostEventType.DONE, self, task_to_run), '')
                self.disassociate_task(task_to_run)
        else:
            # Check memory which is finite & fail the task if insufficient memory is available
            if self._curr_mem + md > self._memory_available.size:
                e = OutOfMemoryException(task_to_run, self)
                task_to_run.task_failure(e)
                self.disassociate_task(task_to_run)
                raise e
            self._curr_mem += md

            # Check how much compute is available
            ef = Core.core_compute_equivalency(required_core_type=ct, given_core_type=self._core.core_type)
            cd = min(cd, (self._core.num_core - self._curr_comp))
            self._curr_comp += cd

            task_to_run.execute(local_hour_of_day, md, cd, ef)
            Log.log_event(HostEvent(HostEvent.HostEventType.EXECUTE, self, task_to_run), '')
        return

    def __update_inf_iter(self) -> None:
        """
        Update the infinite iterator to reflect change to the associated tasks.
        """
        self._inf_task_iter = InfRndIter(list(self._tasks.keys()))
        return

    def __next_task_to_execute(self) -> Task:
        """
        The random next associated task to execute
        :return: The task to execute
        """
        return self._tasks[next(self._inf_task_iter)]

    @classmethod
    def all_hosts(cls) -> List['Host']:
        """
        Return a list of all tasks (Hosts) created at this point in time.
        :return: A list of App(s)
        """
        host_list = []
        all_comp_ids = Compute.all_compute_ids()
        for comp_id in all_comp_ids:
            comp = Compute.get_by_id(comp_id)
            if isinstance(comp, Host):
                host_list.append(comp)
        return host_list

    def all_tasks(self) -> List:
        """
        Create a deepcopy list of all tasks associated with the host at this point in time
        :return: A list of tasks
        """
        task_list = []
        for k in self._tasks.keys():
            task_list.append(deepcopy(self._tasks[k]))
        return task_list

    def __str__(self) -> str:
        """
        Details of the Host as string
        :return: A String containing all details of the host.
        """
        return ''.join(
            (self.name, ':',
             str(self.type), '-',
             'Core:', str(self.core_count), '-',
             'Mem:', str(self.max_memory), '-Mem Util:',
             Util.to_pct(self._curr_mem, self.max_memory), '% '
             )
        )


from AIIntuition.journeys.journey5.randomhostprofile import RandomHostProfile

if __name__ == "__main__":
    for i in range(0, 100):
        c = DataCenter(DataCenter.CountryCode.ICELAND)
        h = Host(c, RandomHostProfile())
        print(h)
